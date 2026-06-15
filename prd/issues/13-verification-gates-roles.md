# Slice 13 — RENOVA: Verification gates & role permissions

**Type:** AFK
**Deep module:** none (cross-cutting; reuses Groups/Permissions + an abstract mixin)
**User stories:** 66, 67, 68

## Parent

PRD: `prd/CMV-KT_Research_Database_PRD.md`

## What to build

The four-eyes verification layer, applied **only** where an error changes a result, plus the finalized role model. This is cross-cutting: it lands after the outcome-critical models exist (serostatus/drug levels in slice 05, episode adjudication in slice 07, genotype calls in slice 10) so the mixin can be attached to each.

A reusable abstract `VerificationMixin` (`entered_by` / `verified_by` / `verified_at` / `is_verified`, enforcing `entered_by != verified_by`) is mixed into outcome-critical fields only — episode adjudication, genotype calls, serostatus, drug levels — so verification effort isn't spent on low-stakes rows. Roles use Django's built-in Groups/Permissions (`data_manager`, `reviewing_clinician`, `data_analyst`, `admin`) with **no bespoke security code**; django-simple-history and django-otp TOTP 2FA are enforced on all roles. Validation lives on the models so the admin, the shell, and the ingest command all enforce the same gate.

## Acceptance criteria

- [ ] `VerificationMixin` is an abstract model enforcing `entered_by != verified_by`; a same-user verify is rejected.
- [ ] The mixin is applied to outcome-critical models only (episode adjudication, genotype calls, serostatus, drug levels) — not to every table.
- [ ] Roles exist purely as Django Groups/Permissions; no custom permission framework is added.
- [ ] django-otp TOTP 2FA is required for every role; django-simple-history records changes on the verified models.
- [ ] The verification gate is enforced at the model layer, so admin/shell/ingest paths all honor it.

## Blocked by

- Blocked by Slice 05 (serostatus, drug levels)
- Blocked by Slice 07 (episode adjudication)
- Blocked by Slice 10 (genotype calls)
