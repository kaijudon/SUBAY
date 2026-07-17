import { execSync } from "node:child_process";
import { createSandbox, claudeCode } from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

// AFK improvement loop: Tester -> (GitHub issues) -> Planner -> Builder <-> Reviewer
// -> back to Tester, until the Tester finds nothing to fix.
//
//   npx tsx .sandcastle/improve-pipeline.mts
//
// The Tester E2E-tests the whole app and files one `afk-tester` GitHub issue per
// finding. For each open issue the Planner/Builder/Reviewer drive a fix to green +
// backpressure-0, and the Reviewer closes the issue. After every issue is handled
// the loop re-runs the Tester to re-test the now-fixed app. ALL_GREEN ends it.
const branch = "agent/afk-improve";
const base = execSync("git branch --show-current").toString().trim();

// All roles use the same model; tune per role if desired.
const tester = claudeCode("claude-opus-4-8", { effort: "medium" });
const planner = claudeCode("claude-opus-4-8", { effort: "medium" });
const builder = claudeCode("claude-opus-4-8", { effort: "medium" });
const reviewer = claudeCode("claude-opus-4-8", { effort: "medium" });

const MAX_LOOPS = 5; // bound the AFK loop: at most this many test->fix passes.
const MAX_REVIEW_ROUNDS = 4; // build<->review rounds per issue.

const TEST_DONE = "<promise>TEST_DONE</promise>";
const ALL_GREEN = "<promise>ALL_GREEN</promise>";
const TEST_BLOCKED = "<promise>TEST_BLOCKED</promise>";
const PLAN_READY = "<promise>PLAN_READY</promise>";
const PLAN_BLOCKED = "<promise>PLAN_BLOCKED</promise>";
const BUILD_DONE = "<promise>BUILD_DONE</promise>";
const BUILD_BLOCKED = "<promise>BUILD_BLOCKED</promise>";
const APPROVED = "<promise>APPROVED</promise>";
const CHANGES = "<promise>CHANGES</promise>";

// One warm worktree on agent/afk-improve for the whole loop. Builder commits fixes
// here, so the next Tester pass re-tests the fixed code on the same branch.
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

async function fail(msg: string): Promise<never> {
  try {
    await box.close();
  } catch {
    /* ignore close errors on the failure path */
  }
  console.error(
    `ABORT (afk-improve): ${msg} Commits (if any) are isolated on ${branch}, NOT merged.`,
  );
  process.exit(1);
}

// Open issues the Tester filed, newest-first by number. Read from the host `gh`
// (already authenticated) between agent runs.
function openTesterIssues(): number[] {
  const out = execSync(
    `gh issue list --label afk-tester --state open --json number --jq '.[].number'`,
  ).toString().trim();
  return out ? out.split("\n").map((n) => Number(n)).sort((a, b) => a - b) : [];
}

for (let loop = 1; loop <= MAX_LOOPS; loop++) {
  console.log(`=== AFK loop ${loop}/${MAX_LOOPS}: Tester E2E pass ===`);

  const test = await box.run({
    name: `tester-loop-${loop}`,
    agent: tester,
    promptFile: "./.sandcastle/tester.md",
    completionSignal: [TEST_DONE, ALL_GREEN, TEST_BLOCKED],
    maxIterations: 20,
  });
  if (test.completionSignal === ALL_GREEN) {
    await box.close();
    console.log(`OK: Tester found nothing to fix after ${loop} loop(s). App is green.`);
    console.log(`Fixes (if any) are on ${branch} (base ${base}, not merged).`);
    process.exit(0);
  }
  if (test.completionSignal !== TEST_DONE) {
    await fail(test.completionSignal === TEST_BLOCKED ? "Tester blocked." : "Tester produced no verdict.");
  }

  const issues = openTesterIssues();
  if (issues.length === 0) {
    await fail("Tester signalled TEST_DONE but no open afk-tester issues were found.");
  }
  console.log(`Tester filed issues: ${issues.map((n) => `#${n}`).join(", ")}`);

  // Planner -> Builder <-> Reviewer per issue (worst-first by the Tester's triage,
  // here simply lowest issue number first).
  for (const issue of issues) {
    console.log(`--- issue #${issue}: plan ---`);
    const promptArgs = { ISSUE: String(issue) };

    const plan = await box.run({
      name: `planner-issue-${issue}`,
      agent: planner,
      promptFile: "./.sandcastle/improve-planner.md",
      promptArgs,
      completionSignal: [PLAN_READY, PLAN_BLOCKED],
      maxIterations: 3,
    });
    if (plan.completionSignal !== PLAN_READY) {
      await fail(plan.completionSignal === PLAN_BLOCKED ? `Planner blocked on #${issue}.` : `Planner produced no plan for #${issue}.`);
    }

    let approved = false;
    for (let round = 1; round <= MAX_REVIEW_ROUNDS; round++) {
      console.log(`--- issue #${issue}: build/review round ${round} ---`);

      const build = await box.run({
        name: `builder-issue-${issue}-r${round}`,
        agent: builder,
        promptFile: "./.sandcastle/improve-builder.md",
        promptArgs,
        completionSignal: [BUILD_DONE, BUILD_BLOCKED],
        maxIterations: 10,
      });
      if (build.completionSignal !== BUILD_DONE) {
        await fail(build.completionSignal === BUILD_BLOCKED ? `Builder blocked on #${issue}.` : `Builder did not finish #${issue}.`);
      }

      const review = await box.run({
        name: `reviewer-issue-${issue}-r${round}`,
        agent: reviewer,
        promptFile: "./.sandcastle/improve-reviewer.md",
        promptArgs,
        completionSignal: [APPROVED, CHANGES],
        maxIterations: 5,
      });
      if (review.completionSignal === APPROVED) {
        approved = true;
        break;
      }
      if (review.completionSignal !== CHANGES) {
        await fail(`Reviewer produced no verdict on #${issue}.`);
      }
      // CHANGES: loop back; Builder reads docs/plans/issue-${issue}-review.md next round.
    }

    if (!approved) {
      await fail(`No approval for #${issue} after ${MAX_REVIEW_ROUNDS} review rounds.`);
    }
    console.log(`OK: issue #${issue} fixed, verified, and closed.`);
  }
  // All issues this pass handled -> loop back to the Tester to re-test E2E.
}

await box.close();
console.error(`Stopped after ${MAX_LOOPS} loops without an ALL_GREEN Tester pass. Fixes are on ${branch}, not merged.`);
process.exit(1);
