import { execSync } from "node:child_process";
import { createSandbox, claudeCode } from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

// Standalone advisor: a single agent gives an independent SECOND OPINION on the
// Planner's plan and the Reviewer's verdict for one already-built slice. It runs
// on the existing agent/slice-NN branch (reads the committed plan/review + the
// slice diff), writes docs/plans/SliceNN-advisor.md, and commits ONLY that file.
// Read-only otherwise; NOT merged. This is a review gate, not part of the
// build<->review loop in main-pipeline.mts.
//
//   npx tsx .sandcastle/advisor-pipeline.mts 15
const slice = process.argv[2] ?? "15";
const branch = `agent/slice-${slice}`;
const base = execSync("git branch --show-current").toString().trim();

// The advisor runs on Fable 5. Fable carries its own reasoning profile, so no
// --effort flag is passed (unlike the opus roles in main-pipeline.mts).
const advisor = claudeCode("claude-fable-5");

const ADVICE_READY = "<promise>ADVICE_READY</promise>";
const ADVICE_BLOCKED = "<promise>ADVICE_BLOCKED</promise>";

// Warm worktree on the existing agent/slice-NN branch. `git worktree add <path>
// <branch>` checks the branch out when it already exists (only invalid refs fall
// back to -b), so the advisor sees exactly what the pipeline built and merged.
const box = await createSandbox({
  branch,
  // containerd image store needs the fully-qualified ref.
  sandbox: docker({ imageName: "docker.io/library/sandcastle:renova_final" }),
  hooks: {
    sandbox: {
      onSandboxReady: [
        { command: "pip install --no-cache-dir -r requirements.txt" },
      ],
    },
  },
});

const advice = await box.run({
  name: `advisor-${slice}`,
  agent: advisor,
  promptFile: "./.sandcastle/advisor.md",
  promptArgs: { SLICE: slice },
  completionSignal: [ADVICE_READY, ADVICE_BLOCKED],
  maxIterations: 10,
});

await box.close();

if (advice.completionSignal !== ADVICE_READY) {
  console.error(
    `ADVISOR did not complete (${advice.completionSignal ?? "no signal"}). ` +
      `Opinion, if any, is on ${branch}.`,
  );
  process.exit(1);
}
console.log(`OK: advisor opinion committed on ${branch} (base ${base}, not merged).`);
console.log(`Read it with: git show ${branch}:docs/plans/Slice${slice}-advisor.md`);
