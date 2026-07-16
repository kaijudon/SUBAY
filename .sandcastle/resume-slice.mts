import { execSync } from "node:child_process";
import { createSandbox, claudeCode } from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";
import { BUILDER_HABITS, REVIEWER_HABITS } from "./fable-habits.mts";

// Resume driver: the Builder already committed work on agent/slice-NN, but the
// run died (e.g. API stream timeout) before review/merge. This skips Planner and
// Builder, starts at the Reviewer against the existing branch HEAD, loops back to
// the Builder only if the Reviewer requests CHANGES, and merges on APPROVED.
//
//   npx tsx .sandcastle/resume-slice.mts 10
const slice = process.argv[2] ?? "10";
const branch = `agent/slice-${slice}`;
const base = execSync("git branch --show-current").toString().trim();

const builder = claudeCode("claude-opus-4-8", { effort: "medium" });
const reviewer = claudeCode("claude-opus-4-8", { effort: "medium" });

const MAX_REVIEW_ROUNDS = 4;

const BUILD_DONE = "<promise>BUILD_DONE</promise>";
const BUILD_BLOCKED = "<promise>BUILD_BLOCKED</promise>";
const APPROVED = "<promise>APPROVED</promise>";
const CHANGES = "<promise>CHANGES</promise>";

// Existing branch with committed work: `git worktree add <path> <branch>` checks
// out its HEAD, so the Reviewer sees the Builder's commit.
const box = await createSandbox({
  branch,
  sandbox: docker({ imageName: "docker.io/library/sandcastle:renova_final" }),
  hooks: {
    sandbox: {
      onSandboxReady: [
        { command: "pip install --no-cache-dir -r requirements.txt" },
      ],
    },
  },
});

async function fail(msg: string): Promise<never> {
  try {
    await box.close();
  } catch {
    /* ignore close errors on the failure path */
  }
  console.error(
    `ABORT (slice ${slice}): ${msg} Commits are isolated on ${branch}, NOT merged.`,
  );
  process.exit(1);
}

const promptArgs = { SLICE: slice };

let approved = false;
for (let round = 1; round <= MAX_REVIEW_ROUNDS; round++) {
  console.log(`--- slice ${slice}: resume review round ${round} ---`);

  const review = await box.run({
    name: `reviewer-${slice}-resume-r${round}`,
    agent: reviewer,
    promptFile: "./.sandcastle/reviewer.md",
    promptArgs: { ...promptArgs, FABLE_HABITS: REVIEWER_HABITS },
    completionSignal: [APPROVED, CHANGES],
    maxIterations: 5,
  });
  if (review.completionSignal === APPROVED) {
    approved = true;
    break;
  }
  if (review.completionSignal !== CHANGES) {
    await fail("Reviewer produced no verdict.");
  }

  // CHANGES: Builder addresses docs/plans/Slice{{SLICE}}-review.md, then re-review.
  const build = await box.run({
    name: `builder-${slice}-resume-r${round}`,
    agent: builder,
    promptFile: "./.sandcastle/builder.md",
    promptArgs: { ...promptArgs, FABLE_HABITS: BUILDER_HABITS },
    completionSignal: [BUILD_DONE, BUILD_BLOCKED],
    maxIterations: 10,
  });
  if (build.completionSignal !== BUILD_DONE) {
    await fail(build.completionSignal === BUILD_BLOCKED ? "Builder blocked." : "Builder did not finish.");
  }
}

if (!approved) {
  await fail(`No approval after ${MAX_REVIEW_ROUNDS} review rounds.`);
}

await box.close();
console.log(`Merging ${branch} into ${base}...`);
execSync(`git merge --no-ff -m "Merge ${branch}" "${branch}"`, { stdio: "inherit" });
console.log(`OK: slice ${slice} approved and merged into ${base}.`);
