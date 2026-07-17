import { createSandbox, claudeCode } from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

// AFK data-entry tester driver (DEC-025). Each iteration runs the whole loop:
// fresh disposable DB -> bulk synthetic ~40-subject dataset -> seeded confirmed
// TOTPDevice -> Playwright login to the OTP-gated admin using a live pyotp code
// -> inspect a ROTATING subset of admin forms (T3/#14) -> file one afk-data-entry
// issue per finding -> emit a promise -> next iteration.
//
// Parallel to main-pipeline.mts, but a single box.run of one hat
// (data-entry-tester.md) instead of the Planner/Builder/Reviewer loop: this hat
// only FINDS and FILES; the reviewed pipeline owns the fix. Each iteration drops
// and re-seeds its scratch DB, so nothing carries over except the rotation
// counter that broadens form coverage. The sandbox is disposable and torn down
// at the end.
//
// Within one usage window the iterations run back-to-back with no cooldown; the
// daily /schedule entry (T4/#15, .sandcastle/systemd/) starts a window at the
// 21:00 UTC usage-limit reset. See .sandcastle/SCHEDULE.md.
//
//   npx tsx .sandcastle/data-entry-tester-pipeline.mts
const tester = claudeCode("claude-opus-4-8", { effort: "medium" });

// The three terminal signals the hat can emit (exactly one per iteration).
const ALL_GREEN = "<promise>ALL_GREEN</promise>";
const TEST_DONE = "<promise>TEST_DONE</promise>";
const TEST_BLOCKED = "<promise>TEST_BLOCKED</promise>";

// Within a usage window (the daily /schedule fire, T4/#15) iterations run
// back-to-back with no cooldown - the Claude usage limit is what stops them, not
// an artificial throttle. This cap is only a runaway guard set well above the
// iterations one reset-to-reset window can afford; a window ends by hitting the
// usage limit long before this.
const MAX_ITERATIONS_PER_WINDOW = 250;

// Fresh sandbox on the current branch. onSandboxReady installs production deps,
// then the sandbox-only test deps (pyotp + playwright, from requirements-dev.txt,
// T1/#12), then the Chromium browser binary Playwright drives. requirements.txt
// stays untouched - these never reach the production box.
const box = await createSandbox({
  sandbox: docker({ imageName: "docker.io/library/sandcastle:subay_final" }),
  hooks: {
    sandbox: {
      onSandboxReady: [
        { command: "pip install --no-cache-dir -r requirements.txt" },
        { command: "pip install --no-cache-dir -r requirements-dev.txt" },
        // Browser binary only - no --with-deps: the system libs are baked into the
        // image as root (see .sandcastle/Dockerfile); --with-deps would re-shell to
        // apt as the non-root agent user and fail.
        { command: "python -m playwright install chromium" },
      ],
    },
  },
});

async function teardown(): Promise<void> {
  try {
    await box.close();
  } catch {
    /* ignore close errors - the sandbox is disposable either way */
  }
}

try {
  const run = await box.run({
    name: "data-entry-tester",
    agent: tester,
    promptFile: "./.sandcastle/data-entry-tester.md",
    completionSignal: [ALL_GREEN, TEST_DONE, TEST_BLOCKED],
    maxIterations: MAX_ITERATIONS_PER_WINDOW,
    // Pin the log path explicitly. In head branch mode (the default for a
    // non-isolated docker sandbox) sandcastle's box.run handle path derives the
    // default log filename from an undefined `branch`, which throws in
    // buildLogFilename; supplying `logging` skips that derivation entirely.
    logging: { type: "file", path: "./.sandcastle/logs/data-entry-tester.log" },
  });

  const signal = run.completionSignal;
  if (signal === ALL_GREEN) {
    console.log("OK: admin data-entry UI green - no finding filed.");
  } else if (signal === TEST_DONE) {
    console.log("OK: iteration filed one or more afk-data-entry issues.");
  } else if (signal === TEST_BLOCKED) {
    console.error("BLOCKED: iteration could not run to completion (see run log).");
    process.exitCode = 1;
  } else {
    console.error("ABORT: hat emitted no terminal promise signal.");
    process.exitCode = 1;
  }
} finally {
  // Always tear the sandbox (and its scratch DB) down; nothing persists.
  await teardown();
}
