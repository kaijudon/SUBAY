# Context

## Recent commits (last 10)

!`git log --oneline -10`

# Task — RENOVA Slice 13: Verification gates & role permissions

## Context (carry forward)
- Stack: Django + `renova` package, app `renova/registry/`. Validation lives on
  the models. Test harness inside this sandbox: `python -m pytest -q`.
- Slices 00–12 are merged and green. This is cross-cutting and lands AFTER the
  outcome-critical models exist: serostatus/drug levels (slice 05), episode
  adjudication (slice 07), genotype calls (slice 10).
- Source of truth: `prd/issues/13-verification-gates-roles.md`. Parent spec:
  `prd/CMV-KT_Research_Database_PRD.md`. Read the card before planning.

## Goal (target state)
The four-eyes verification layer, applied ONLY where an error changes a result,
plus the finalized role model. A reusable abstract mixin is attached to
outcome-critical models so verification effort isn't spent on low-stakes rows.

## Scope
IN — only this slice:
- Abstract `VerificationMixin` (`entered_by` / `verified_by` / `verified_at` /
  `is_verified`) enforcing `entered_by != verified_by`.
- Mixed into OUTCOME-CRITICAL models ONLY: episode adjudication, genotype calls,
  serostatus, drug levels — NOT every table.
- Roles via Django built-in Groups/Permissions: `data_manager`,
  `reviewing_clinician`, `data_analyst`, `admin` — NO bespoke security code.
- django-otp TOTP 2FA enforced on all roles; django-simple-history on the
  verified models.
- Validation on the models so admin, shell, and ingest command all enforce the
  same gate.

OUT — do NOT build now:
- New domain models; this slice attaches the mixin + roles to existing ones.

## Constraints
MUST:
- Keep all existing tests passing; ADD tests, never weaken them.
- `VerificationMixin` is ABSTRACT and rejects a same-user verify.
- Apply the mixin to outcome-critical models only.
- Roles are pure Django Groups/Permissions; no custom permission framework.
- The gate is enforced at the MODEL layer (admin/shell/ingest all honor it).

MUST NOT:
- Add a bespoke security/permission framework.
- Apply the mixin to low-stakes tables.
- Weaken any prior slice's de-id export (chokepoint stays intact; dates as
  day-offsets).
- Touch `.env`, secrets, settings DB credentials, `deploy/`, or CI config.
- Add a Python dependency without stating why in the plan first (django-otp /
  django-simple-history are already present).

## Acceptance criteria (all must pass — binary)
- [ ] `VerificationMixin` is an abstract model enforcing `entered_by != verified_by`; a same-user verify is rejected.
- [ ] The mixin is applied to outcome-critical models only (episode adjudication, genotype calls, serostatus, drug levels) — not to every table.
- [ ] Roles exist purely as Django Groups/Permissions; no custom permission framework is added.
- [ ] django-otp TOTP 2FA is required for every role; django-simple-history records changes on the verified models.
- [ ] The verification gate is enforced at the model layer, so admin/shell/ingest paths all honor it.

## Workflow (RGR — Red → Green → Repeat → Refactor)
1. **Explore** — read `prd/issues/13-verification-gates-roles.md` and the parent
   PRD. Read the relevant source files and existing tests before any code.
2. **Plan** — decide the smallest change that satisfies the acceptance criteria.
   If a new Python dependency is unavoidable, state why here first.
3. **Execute** — write a failing test first, then the implementation to pass it.
   Build the mixin's same-user-reject test-first, then attach to the four
   outcome-critical models. Confirm the gate fires on the shell/ingest path, not
   just admin.
4. **Verify** — all must pass before committing:
   - `python -m pytest -q` (old + new, full suite green)
   - `python manage.py makemigrations --check` (migrations clean)
   - `python scripts/backpressure.py` (backpressure collector exits 0)
5. **Commit** — a single git commit. The message MUST:
   - Start with `Slice 13:` prefix
   - Name the task and PRD reference (`prd/issues/13-verification-gates-roles.md`)
   - List key decisions made
   - List files changed

## Rules
- Do not leave commented-out code or TODO comments in committed code.
- Do not weaken or delete existing tests to make the suite pass.
- If blocked (missing context, failing tests you cannot fix), stop and explain
  the blocker rather than committing a partial or broken change.

# Done
When every acceptance-criteria box is satisfied, the full suite is green,
migrations are clean, the backpressure collector exits 0, and the change is
committed — verify each acceptance criterion yourself, then output the completion
signal:

<promise>COMPLETE</promise>
