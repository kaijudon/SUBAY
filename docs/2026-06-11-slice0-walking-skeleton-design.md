# Slice 0 — RENOVA Walking Skeleton — Design

*Fresh build under `renova_final/`. Source card: `prd/issues/00-walking-skeleton.md`.
Source PRD: `prd/CMV-KT_Research_Database_PRD.md` (O8 / Topic #7-D).*

## Goal

The thinnest end-to-end path through every layer of RENOVA (RENal transplant
Observational Viral Archive) so the deep-module slices have a spine to attach to:
a Data Manager logs in with TOTP 2FA, enters a pseudonymous recipient + one visit +
one CMV serology in the customized Django admin, and runs an export that emits a
de-identified CSV with no calendar dates.

## Stack (locked)

Django 5.1 + PostgreSQL (sqlite for tests via `DATABASE_URL`), customized Django
admin as the data-entry interface, django-otp (TOTP 2FA), django-simple-history
audit, Django Groups/Permissions roles. Served by gunicorn over a Unix socket behind
nginx HTTPS bound to `127.0.0.1`; secrets from a root-owned `0600` systemd env file.

## Architecture

Single `renova` project, single `registry` app ("one tidy workspace" — split later
when there is enough to justify it). Validation lives on the models, so the admin,
the shell, and any future ingest command all enforce the same rules.

### Models (`registry/models.py`)

- **`BaseSubject`** — abstract (`subject_id` PK string + format validator,
  `date_of_birth`, `sex`). Emits no table.
- **`Recipient(BaseSubject)`** — `kt_date` (transplant = day 0 anchor),
  `donor_serostatus`, `recipient_serostatus`. `age` and `risk_stratum` are
  `@property` (derived, never stored).
- **`Donor(BaseSubject)`** — thin.
- **`RecipientVisit`** — FK→Recipient, `visit_date`.
- **`CMVSerology`** — nullable FK→RecipientVisit **and** nullable FK→Donor with an
  **exactly-one-parent** rule; numeric `value` (Snibe Maglumi 600 AU/mL) with
  `is_positive` derived at the 2.0 AU/mL binary threshold.

### Key design choices

1. **Abstract `BaseSubject`, no table.** Shared identity columns are copied into
   `Recipient`/`Donor`; there is no `basesubject` table and no cross-table join.
2. **Derived, never stored.** `age` (at `kt_date`), `risk_stratum` (D/R serostatus),
   `is_positive` are computed on read, so a stored fact and its computed value can
   never disagree.
3. **Exactly-one-parent enforced twice.** `clean()` gives the data-entry clerk a
   readable error; a DB `CheckConstraint` makes a malformed row physically
   impossible on every write path (admin, shell, future bulk import).
4. **Opaque subject IDs.** Format `[S|D]CMV[R|D][NN]` is validated, never generated —
   the identity map lives outside the app. `"07"` is a string, never coerced to `7`.
5. **OTP admin via a module boundary.** `RenovaAdminSite(OTPAdminSite)` lives in its
   own `sites.py`; `AdminConfig.default_site` points at it so every admin login
   requires TOTP with no bespoke security code. The class is kept out of `admin.py`
   to avoid re-entrant lazy-site resolution during admin autodiscover.

### Export / de-id (`export_analysis_set`)

A management command writes one CSV per model to `analysis_sets/<version>/`, converts
every date to an **integer day-offset from the recipient's `kt_date`** (transplant =
day 0), drops date-of-birth in favor of derived `age`, runs a calendar-date leak
check that refuses to emit, and refuses to overwrite a frozen version. Slice 01
hardens this into the full audited chokepoint (`manifest.json`, per-file SHA-256, a
full identifier-leak refuse).

### Access / audit

Four Django Groups (`data_manager`, `reviewing_clinician`, `data_analyst`, `admin`) via a
data migration; django-otp TOTP on all logins; django-simple-history on `Recipient`,
`RecipientVisit`, `CMVSerology` (plus `Donor`).

### Deploy spine (artifacts; standup is HITL / Slice 15)

`deploy/` holds the gunicorn Unix-socket config, the `127.0.0.1`-only nginx HTTPS
config, and the systemd unit with a root-owned `0600` `EnvironmentFile`. Standing
these up on the real SPMC box is the Slice 15 checkpoint.

## Testing

`pytest` + `pytest-django` (established here as prior art for every later slice):
abstract-no-table, subject-id-as-string, format validator, exactly-one (clean + DB
constraint, both & neither), derived age/risk_stratum, simple-history, role Groups,
admin inlines/readonly-derived/OTP-enforced, export day-offsets + no-calendar-date +
no-DOB + frozen-version refusal, and a smoke test asserting exactly-one + a date-safe
export. 21 tests, green.

## Out of scope (later slices)

Other lab models, clinical events, biobank ledger, genotyping (deep modules);
manifest/SHA-256/full leak-refuse (01); `VerificationMixin` (13); self-service TOTP
enrollment; LUKS/pgcrypto and the full production-hardening standup (15).
