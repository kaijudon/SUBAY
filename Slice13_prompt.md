# Task — SUBAY Slice 13: Verification gates & role permissions

## Context (carry forward)
- Stack: Django + `subay` package, app `subay/registry/`. Validation lives on
  the models. Test harness: `conda run -n subay_env python -m pytest -q`.
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

## Approach
Thin slice — cross-cutting; reuses Groups/Permissions + an abstract mixin. Build
the mixin's same-user-reject test-first, then attach to the four outcome-critical
models. Confirm the gate fires on the shell/ingest path, not just admin.

## Done when
Every acceptance-criteria box is satisfied, the full suite is green
(`conda run -n subay_env python -m pytest -q`, old + new), migrations are clean
(`conda run -n subay_env python manage.py makemigrations --check`), the
backpressure collector exits 0
(`conda run -n subay_env python scripts/backpressure.py`), and the Reviewer hat
approves. When the Reviewer approves, print LOOP_COMPLETE.
