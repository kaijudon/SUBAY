import { createSandbox, claudeCode } from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

// AFK data-entry tester driver (DEC-025). One THIN tracer iteration through the
// whole loop: fresh disposable DB -> seeded confirmed TOTPDevice -> Playwright
// login to the OTP-gated admin using a live pyotp code -> probe ONE admin form
// -> file one afk-data-entry issue per finding -> emit a promise -> tear down.
//
// Parallel to main-pipeline.mts, but a single box.run of one hat
// (data-entry-tester.md) instead of the Planner/Builder/Reviewer loop: this hat
// only FINDS and FILES; the reviewed pipeline owns the fix. Nothing persists to a
// next run - the sandbox and its scratch DB are disposable and torn down at the end.
//
//   npx tsx .sandcastle/data-entry-tester-pipeline.mts
const tester = claudeCode("claude-opus-4-8", { effort: "medium" });

// The three terminal signals the hat can emit (exactly one per iteration).
const ALL_GREEN = "<promise>ALL_GREEN</promise>";
const TEST_DONE = "<promise>TEST_DONE</promise>";
const TEST_BLOCKED = "<promise>TEST_BLOCKED</promise>";

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
    maxIterations: 12,
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
