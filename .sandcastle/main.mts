import { basename } from "node:path";
import { run, claudeCode } from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

// Single-slice driver. The bash wrapper (.sandcastle/run-slices.sh) calls this
// once per slice, passing the prompt file as the first CLI arg.
//
// Commits land on a per-slice branch (agent/slice-NN), NOT on HEAD — so a failed
// slice never pollutes the mainline. On success the bash wrapper merges the
// branch into HEAD before the next slice runs; on failure it leaves the branch
// for review.
//
// Run one slice directly:
//   npx tsx .sandcastle/main.mts .sandcastle/prompt-09.md
const promptFile = process.argv[2] ?? "./.sandcastle/prompt-09.md";

// prompt-09.md -> "09" -> agent/slice-09
const sliceId = basename(promptFile).replace(/^prompt-/, "").replace(/\.md$/, "");
const branch = `agent/slice-${sliceId}`;

const result = await run({
  // A name for this run, shown as a prefix in log output.
  name: `renova-slice-${sliceId}`,

  // Sandbox provider — runs the agent inside an isolated container.
  sandbox: docker(),

  // Agent: Opus 4.8 at medium reasoning effort.
  agent: claudeCode("claude-opus-4-8", { effort: "medium" }),

  // Path to the prompt file for this slice (from the CLI arg above). Shell
  // expressions inside are evaluated in the sandbox at the start of each
  // iteration, so the agent always sees a fresh `git log`.
  promptFile,

  // Iterations the agent gets to reach <promise>COMPLETE</promise> for one slice.
  maxIterations: 10,

  // Commits land on agent/slice-NN, branched from HEAD. Nothing merges to HEAD
  // automatically — the bash wrapper merges only after a successful run, so a
  // failed slice's commits stay isolated on the branch for review/rollback.
  branchStrategy: { type: "branch", branch },

  // Lifecycle hooks. The Dockerfile already installs requirements at build time;
  // this re-runs pip as a safety net in case requirements.txt changed since the
  // image was built.
  hooks: {
    sandbox: {
      onSandboxReady: [
        { command: "pip install --no-cache-dir -r requirements.txt" },
      ],
    },
  },
});

// An incomplete run still resolves successfully (no throw), so the bash driver's
// `set -e` cannot see it. completionSignal is undefined when the agent hit the
// iteration limit without emitting <promise>COMPLETE</promise>. Exit nonzero so
// the loop aborts instead of merging unfinished work.
if (!result.completionSignal) {
  console.error(
    `FAILED: ${promptFile} ran ${result.iterations.length} iteration(s) ` +
      `without emitting the completion signal. Commits (if any) are isolated ` +
      `on ${branch} and were NOT merged. Aborting.`,
  );
  process.exit(1);
}

console.log(
  `OK: ${promptFile} completed in ${result.iterations.length} iteration(s). ` +
    `Commits are on ${branch}, ready to merge.`,
);
