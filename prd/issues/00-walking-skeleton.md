# Slice 00 — RENOVA: Walking skeleton & deploy spine

**Type:** HITL (design-review checkpoint on scaffold + deployment conventions)
**Deep module:** none (this is the spine the deep modules attach to)
**User stories:** 1, 2, 66, 67, 69, 70, 80

## Parent

PRD: `prd/CMV-KT_Research_Database_PRD.md`

## What to build

The thinnest end-to-end path through every layer of **RENOVA** (RENal transplant Observational Viral Archive), so subsequent deep-module slices have a spine to attach to. A Data Manager logs in with TOTP 2FA, enters a pseudonymous recipient + one visit + one lab result in the customized Django admin, and runs an export command that emits a de-identified CSV with no calendar dates.

Stack per PRD (O8 / Topic #7-D): Django + PostgreSQL (project/package `renova`), customized Django admin as the data-entry interface, django-otp (TOTP 2FA) on all roles, django-simple-history audit, Django Groups/Permissions roles. nginx/gunicorn HTTPS over a Unix socket, app bound to `127.0.0.1` only. Secrets in a root-owned `0600` env file loaded by systemd (never in repo/settings). Validation lives on the models. A `pytest`/`pytest-django` harness is established here as prior art for every later slice.

Models (minimal): abstract `BaseSubject` (no table) → concrete `Recipient` and `Donor`; `RecipientVisit`; one lab model `CMVSerology` carrying the dual-FK "exactly one parent" rule. Subject ID is a string PK in format `[S|D]CMV[R|D][NN]`. DOB stored; age/risk_stratum derived `@property`.

A minimal `export_analysis_set` management command writes one CSV per existing model to `analysis_sets/<version>/`, converting every date to an integer day-offset from the recipient's `kt_date` (transplant = day 0). Slice 01 hardens this into the full audited chokepoint.

## Acceptance criteria

- [ ] `Recipient` and `Donor` inherit `subject_id`/`date_of_birth`/`sex` from abstract `BaseSubject`; no `basesubject` table exists in the DB.
- [ ] `subject_id` is read/stored as a string (e.g. `SCMVR07`), never coerced to a number.
- [ ] Roles `data_entry`, `adjudicator`, `analyst-readonly`, `admin` exist as Django Groups; login requires TOTP 2FA; admin/login header reads "RENOVA".
- [ ] django-simple-history records create/update on `Recipient`, `RecipientVisit`, `CMVSerology`.
- [ ] `CMVSerology` enforces exactly-one of (recipient-visit FK, donor FK) at the model layer.
- [ ] Admin shows visit→labs as inlines; age and risk_stratum render as derived (read-only), not editable columns.
- [ ] `export_analysis_set` writes per-model CSV with all dates as integer day-offsets from `kt_date`; no calendar date and no name/MRN/address appears in any output file.
- [ ] App binds `127.0.0.1` only, served via nginx/gunicorn over a Unix socket; secrets load from a systemd-supplied env file, not settings.
- [ ] `pytest` harness runs green in CI/local; one smoke test asserts the exactly-one constraint and one asserts the export emits no calendar date.
- [ ] Demo passes: TOTP login → enter recipient + visit + serology → export → inspect CSV shows day-offsets + pseudonym only.

## Blocked by

None - can start immediately.
