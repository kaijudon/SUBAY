# AGENTS.md

## What this project is

SUBAY (**REN**al transplant **O**bservational **V**iral **A**rchive) is a self-hosted
Django webapp that is the single **system-of-record** for the study *"Host Clinical
Status and Characterization of CMV in Kidney Transplant Patients in Region XI"*
(Bad-ang et al., SPMC; DOST-PCHRD 2023-08-A2-PCHRD-CORE-TB-16258). One Data Manager
captures a 6-month longitudinal, multi-matrix research dataset — clinical labs, CMV
viral loads, drug levels, clinical events, a physical biobank of residual aliquots, and
a CMV genotyping pipeline — for ~40 kidney-transplant recipients plus living donors,
then hands a clean, de-identified snapshot to an R analyst who runs the locked
Statistical Analysis Plan.

SUBAY's job is narrow and load-bearing: **capture data, enforce the study's operational
rules, derive the analysis-ready variables, and ship a frozen de-identified export.** It
is Django as system-of-record + derived-variable engine + the single de-identification
chokepoint. It is **not** a pipeline orchestrator and **not** a statistics engine — the
heavy stats (mixed-effects, Kaplan-Meier, Wilson CIs, Mann-Whitney, genotype
concordance) run in R against the frozen export. SUBAY sensitive data is Personal
Information under RA 10173 (PH Data Privacy Act); de-identification is a hard legal
requirement, not a nicety.

This file is the canonical architecture and workflow guide for the current app.
`prd/CMV-KT_Research_Database_PRD.md` governs changes to the app — it is the product
requirement each work slice is built against. Its own source of truth is
`cmv_grilling_session.md` (the resolved-decisions record from the `/grill-me`
interrogation of the protocol, SAP, and DB design); where wording disagrees, the
session's locked decision wins. Consequential build-time decisions are journaled in
`docs/decisions/DECISIONS.md` (DEC-NNN entries).

## Stack and layout

- **Stack (locked):** Django + PostgreSQL (prod) / SQLite (test) + `django-simple-history`
  + `django-otp` (TOTP 2FA on all roles) + a customized Django **admin** as the sole
  data-entry interface. Files on a LUKS-encrypted volume via `FileField` (never DB
  blobs). Sensitive columns via pgcrypto. nginx/gunicorn HTTPS over a Unix socket,
  `127.0.0.1`-only. Self-hosted on one SPMC-sited workstation; zero DDH accounts.
- **Django project package:** `subay/` — `settings.py`, `urls.py`, `asgi.py`,
  `wsgi.py`. Human-facing name "SUBAY"; package name lowercase `subay`.
- **Single app:** `subay/registry/` holds the whole domain. Key modules:
  - `models.py` — every model (subjects, visits, labs, biobank, genotyping, safety).
    **Validation lives on the models** (`clean()` + DB `CheckConstraint`), so admin,
    shell, and ingest paths all enforce the same rules.
  - `scheduling.py` — closure-day forward-shift logic (nominal → first operating day).
  - `episodes.py` — CMV-episode deriver over the long viral-load table.
  - `attribution.py` — Obj 5 source-attribution + genotype-concordance grading.
  - `resistance.py` — UL97/UL54 resistance rollups.
  - `safety.py` — release-timeliness flag (threshold/window as named constants).
  - `validators.py` — shared field validators.
  - `admin.py`, `admin_config.py`, `sites.py` — OTP-enforced admin site
    (`SubayAdminSite` subclasses `OTPAdminSite`; replaces `django.contrib.admin`).
  - `management/commands/` — `export_analysis_set.py` (the de-identification
    chokepoint) and `ingest_genotyping.py`.
  - `tests/` — pytest suite, one `test_*.py` per domain area (~420 tests).
- **Templates / static:** `templates/admin/base_site.html` and `static/admin/css/`
  brand the admin. Project templates win over contrib defaults.
- **Deploy:** `deploy/` — gunicorn/nginx/systemd templates, `RUNBOOK.md`, `CHECKLIST.md`,
  `LAPTOP-DEPLOY.md`. Standing up the real box is a Slice 15 HITL checkpoint, not merged AFK.
- **Specs / process:** `prd/` (PRD + per-issue cards under `prd/issues/`), `docs/plans/`
  (per-slice plans), `docs/decisions/DECISIONS.md`, `SliceNN_prompt.md` at root.
- **Env:** conda env `subay_env` (`environment.yml`) or `.venv/`. `pytest.ini` sets
  `DJANGO_SETTINGS_MODULE=subay.settings`, SQLite default, `--reuse-db`.

## Ubiquitous language

Use these exact terms; they are the study's operational definitions, not loose synonyms.

- **Subject ID** — pseudonymous opaque **string** `[S|D]CMV[R|D][NN]` (e.g. `SCMVR07`).
  Never coerced to int; `"07"` is not `7`. The DB holds no name, MRN, or address.
- **Recipient / Donor** — the two `BaseSubject` types. Recipients carry the full visit
  timeline; donors are lightweight (one draw, at most one baseline serology).
- **Visit** — the data spine. Six scheduled recipient timepoints (pre-KT, day
  7/30/90/120/180). Stores both **nominal day** (KT date + offset) and **actual draw
  date**. Labs attach to a visit.
- **Closure-shift** — a visit landing on a hospital/lab closure day shifts *forward* to
  the first day clinic **and** lab both operate, recorded with `closure_reason` and
  `shift_days_from_nominal`. Consecutive closures = one stretch, one forward shift.
- **+3-day cap** — an actual date more than +3 days off nominal is forced to
  `completion_status = missed_visit`. Enforced by the model.
- **completion_status** — recipient state (enrolled / withdrawn / died / lost_to_followup
  / graft_loss / missed_visit / completed). Drives the D1-plus-replacement completer
  cohort and CONSORT flow.
- **CMV episode** — derived, never stored: starts at first QNAT ≥ 34.5 IU/mL (LoD = LoQ =
  34.5, COBAS 5000), ends at first single negative, every post-resolution positive is a
  **new** episode, no gap.
- **Wide vs long** — low-variability co-drawn panels stored **wide** (serology, TBNK
  seven-subset); unpredictably-repeating measures stored **long** (viral loads).
- **Derived value** — computed on the fly, never stored: age (from DOB), eGFR (CKD-EPI
  2021 race-free from raw creatinine; any lab-reported eGFR ignored), cd4_cd8_ratio,
  risk_stratum (from D/R serostatus). Stored facts and computed values can never disagree.
- **Event-sourced biobank** — remaining aliquot volume and thaw count are **derived** from
  an append-only event log (`Aliquot` → `ThawEvent` → `ConsumptionEvent`). Single-use /
  no-refreeze guard. The ledger cannot lie about history.
- **Provenance is first-class** — genotyping records tube → `PipelineRun` → `GenotypeCall`
  with SHA-256-named append-only raw files. SUBAY records provenance, does not run tools.
- **Four-eyes verification** (`VerificationMixin`) — outcome-critical rows, once
  `is_verified=True`, require `verified_by != entered_by` + `verified_at`. Dual-guarded:
  `clean()` for a friendly error, DB `CheckConstraint` for the bare-save path.
- **Export chokepoint** — `export_analysis_set` writes a versioned frozen de-identified
  CSV snapshot with a SHA-256 manifest; calendar dates become **integer day-offsets from
  transplant**. R never touches the live PHI database.
- **Design principles** (recurring): derive don't store · event-source append-only
  changes · provenance is first-class · human judgment is a field, not an inference ·
  wide-vs-long by variability with a confounder override.

## Teaching system

"End-to-end" here means the **pytest suite exercising the real Django stack** — models,
constraints, derivers, admin registration, and the export management command — not a
browser driver. There is no Playwright/Selenium layer.

Run it:

```sh
conda run -n subay_env python -m pytest -q      # or: .venv/bin/python -m pytest -q
```

**What E2E covers:**

- **Model-layer rules** — `clean()` and DB `CheckConstraint` behavior: subject-ID
  string-ness, exactly-one-parent FKs, +3-day cap, four-eyes verification, append-only
  guards, single-use biobank.
- **Derivers** — episodes, closure-shift scheduling, eGFR/age/ratio/risk, attribution
  and concordance grading, resistance rollups, safety release-timeliness — tested as pure
  functions and through the models.
- **The export chokepoint round-trip** — that `export_analysis_set` emits day-offsets (not
  calendar dates), the right columns, and a valid SHA-256 manifest; that leak-shaped
  fields (e.g. `verified_at`) never enter a `*_COLUMNS` list.
- **Admin wiring** — models are registered, roles/permissions resolve, OTP site loads.
- **History** — `django-simple-history` records changes.

**What E2E cannot cover — verify by hand / defer to HITL:**

- **Postgres-only behavior** — tests run on SQLite (`pytest.ini`). pgcrypto column
  encryption and any Postgres view/window-function path are not exercised; verify on the
  real Postgres box.
- **Browser admin interactions** — inline JS, TOTP device enrollment, actual login flow.
- **Deployment & ops** — nginx/gunicorn/systemd, LUKS volume, HTTPS cert, backups,
  auto-reboot-into-locked-disk footguns. These are the Slice 15 HITL checkpoint
  (`deploy/RUNBOOK.md`, `deploy/CHECKLIST.md`).
- **Physical world** — that the biobank ledger matches the real freezer; that the
  genotyping raw files came from the tube claimed.
- **The statistics** — R runs the SAP against the frozen export; SUBAY only guarantees
  the export contract, not the model fits.

## Project conventions

- **Slice workflow.** Work ships as vertical slices. Read the slice card
  (`prd/issues/NN-*.md`) and parent PRD **before** planning; write the plan to
  `docs/plans/SliceNN-plan.md`; journal consequential decisions as DEC-NNN in
  `docs/decisions/DECISIONS.md`. The session record and PRD are the source of truth — a
  locked decision wins over any looser wording.
- **Simplicity First.** No new Python dependency without stating why in the plan first.
  Prefer a `@property` or pure function over a stored column, a view, or a config knob
  that nothing yet needs.
- **Validation on the models.** Every rule lives in `clean()` **and** a DB
  `CheckConstraint` where a bare-save path (shell/ingest) could bypass forms. Nullable
  gate fields so the guard bites only when it should, keeping existing fixtures green.
- **Derive, don't store.** If a value is a pure function of stored facts (age, eGFR,
  ratios, risk, episodes, biobank volume), compute it — never persist it.
- **Append-only / event-sourced** for anything with custody or history (biobank,
  genotyping raw files). No mutation, no delete; add an event.
- **De-identification is sacred.** No calendar date, name, MRN, or address may reach the
  export — only integer day-offsets from transplant. Any field of `drawn_date` shape must
  never enter a `*_COLUMNS` list. R never touches live PHI.
- **Subject IDs stay strings.** Always.
- **Tests: add, never weaken.** Keep the full suite green; every slice adds tests.
  `django-simple-history` on new records.
- **Commits/PRs.** Do not add a `Co-Authored-By: Claude` trailer.
