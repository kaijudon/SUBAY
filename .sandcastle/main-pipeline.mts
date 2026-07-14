import { execSync } from "node:child_process";
import { createSandbox, claudeCode } from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";
import {
  PLANNER_HABITS,
  BUILDER_HABITS,
  REVIEWER_HABITS,
} from "./fable-habits.mts";

// Multi-agent slice driver: Planner -> Builder <-> Reviewer (feedback loop).
// Ports the Ralph hats.yml pipeline. One generic set of role prompts
// (planner.md / builder.md / reviewer.md), parameterized per slice via {{SLICE}}
// and armed with Fable's five-gate working method via {{FABLE_HABITS}}
// (role-tailored blocks in fable-habits.mts).
//
// Run one slice:
//   npx tsx .sandcastle/main-pipeline.mts 09
const slice = process.argv[2] ?? "09";
const branch = `agent/slice-${slice}`;
const base = execSync("git branch --show-current").toString().trim();

// All three roles use the same model; tune per role if desired.
const planner = claudeCode("claude-opus-4-8", { effort: "medium" });
const builder = claudeCode("claude-opus-4-8", { effort: "medium" });
const reviewer = claudeCode("claude-opus-4-8", { effort: "medium" });

const MAX_REVIEW_ROUNDS = 4;

// Signals each role emits. completionSignal accepts an array; the matched string
// is returned on the result, which routes the build<->review loop.
const PLAN_READY = "<promise>PLAN_READY</promise>";
const PLAN_BLOCKED = "<promise>PLAN_BLOCKED</promise>";
const BUILD_DONE = "<promise>BUILD_DONE</promise>";
const BUILD_BLOCKED = "<promise>BUILD_BLOCKED</promise>";
const APPROVED = "<promise>APPROVED</promise>";
const CHANGES = "<promise>CHANGES</promise>";

// One warm worktree on agent/slice-NN for the whole pipeline. pip install runs
// once at sandbox creation (the repo is bind-mounted, so requirements.txt is there).
const box = await createSandbox({
  branch,
  // Docker's containerd image store only resolves fully-qualified refs; the bare
  // name `sandcastle:renova_final` fails `docker image inspect`, so pin the full ref.
  sandbox: docker({ imageName: "docker.io/library/sandcastle:renova_final" }),
  hooks: {
    sandbox: {
      onSandboxReady: [
        { command: "pip install --no-cache-dir -r requirements.txt" },
      ],
    },
  },
});

// Tear the worktree down, then abort. close() before exit so a failed slice
// doesn't leak its worktree; commits remain on the branch for review.
async function fail(msg: string): Promise<never> {
  try {
    await box.close();
  } catch {
    /* ignore close errors on the failure path */
  }
  console.error(
    `ABORT (slice ${slice}): ${msg} Commits (if any) are isolated on ${branch}, NOT merged.`,
  );
  process.exit(1);
}

const promptArgs = { SLICE: slice };

// 1. Planner
const plan = await box.run({
  name: `planner-${slice}`,
  agent: planner,
  promptFile: "./.sandcastle/planner.md",
  promptArgs: { ...promptArgs, FABLE_HABITS: PLANNER_HABITS },
  completionSignal: [PLAN_READY, PLAN_BLOCKED],
  maxIterations: 3,
});
if (plan.completionSignal !== PLAN_READY) {
  await fail(plan.completionSignal === PLAN_BLOCKED ? "Planner blocked." : "Planner produced no plan.");
}

// 2. Builder <-> Reviewer feedback loop
let approved = false;
for (let round = 1; round <= MAX_REVIEW_ROUNDS; round++) {
  console.log(`--- slice ${slice}: build/review round ${round} ---`);

  const build = await box.run({
    name: `builder-${slice}-r${round}`,
    agent: builder,
    promptFile: "./.sandcastle/builder.md",
    promptArgs: { ...promptArgs, FABLE_HABITS: BUILDER_HABITS },
    completionSignal: [BUILD_DONE, BUILD_BLOCKED],
    maxIterations: 10,
  });
  if (build.completionSignal !== BUILD_DONE) {
    await fail(build.completionSignal === BUILD_BLOCKED ? "Builder blocked." : "Builder did not finish.");
  }

  const review = await box.run({
    name: `reviewer-${slice}-r${round}`,
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
  // CHANGES: loop back; Builder reads docs/plans/Slice{{SLICE}}-review.md next round.
}

if (!approved) {
  await fail(`No approval after ${MAX_REVIEW_ROUNDS} review rounds.`);
}

// 3. Tear down the worktree, then merge the approved branch into the mainline so
// the next slice builds on it.
await box.close();
console.log(`Merging ${branch} into ${base}...`);
execSync(`git merge --no-ff -m "Merge ${branch}" "${branch}"`, { stdio: "inherit" });
console.log(`OK: slice ${slice} approved and merged into ${base}.`);
