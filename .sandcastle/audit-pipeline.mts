import { execSync } from "node:child_process";
import { createSandbox, claudeCode } from "@ai-hero/sandcastle";
import { docker } from "@ai-hero/sandcastle/sandboxes/docker";

// One-off cumulative auditor: a single Reviewer agent audits the whole
// subay/registry codebase (merged slices 01–10) on an isolated branch and
// commits its findings report. Read-only except for the report; NOT merged.
//
//   npx tsx .sandcastle/audit-pipeline.mts
const branch = "agent/audit-slices-01-10";
const base = execSync("git branch --show-current").toString().trim();

const auditor = claudeCode("claude-opus-4-8", { effort: "medium" });

const AUDIT_DONE = "<promise>AUDIT_DONE</promise>";
const AUDIT_BLOCKED = "<promise>AUDIT_BLOCKED</promise>";

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

const audit = await box.run({
  name: "auditor-01-10",
  agent: auditor,
  promptFile: "./.sandcastle/audit.md",
  completionSignal: [AUDIT_DONE, AUDIT_BLOCKED],
  maxIterations: 20,
});

await box.close();

if (audit.completionSignal !== AUDIT_DONE) {
  console.error(`AUDIT did not complete (${audit.completionSignal ?? "no signal"}). Report, if any, is on ${branch}.`);
  process.exit(1);
}
console.log(`OK: audit complete. Report committed on ${branch} (base ${base}, not merged).`);
console.log(`Read it with: git show ${branch}:docs/reviews/audit-slices-01-10.md`);
