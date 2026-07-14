# Task — SUBAY Slice 01: Export / de-id chokepoint

## Context (carry forward)
- Stack: Django + `subay` package, app `subay/registry/`. Validation lives on
  the models. Test harness: `conda run -n subay_env python -m pytest -q` (pytest-django).
- Slice 00 is merged and green (21 tests). This slice EXTENDS it; it does not
  rewrite it.
- Source of truth: `prd/issues/01-export-de-id-chokepoint.md`. Parent spec:
  `prd/CMV-KT_Research_Database_PRD.md`. Read the card before planning.
- Current export lives at
  `subay/registry/management/commands/export_analysis_set.py` and already emits
  per-model CSVs with day-offsets. Harden THAT file — do not start over.

## Goal (target state)
`export_analysis_set` is the single audited de-identification chokepoint: one run
produces a versioned, frozen `analysis_sets/<version>/` directory — one
normalized CSV per model, every date an integer day-offset from the recipient's
`kt_date` (transplant = day 0), a `manifest.json`, and an identifier-leak check
that REFUSES to emit (non-zero exit, nothing written) if any identifier would
leak.

## Scope
IN — only this slice:
- Versioned frozen output dir + reproducible per-file SHA-256.
- `manifest.json` (row counts, per-file SHA-256, per-column type expectations).
- Identifier-leak refusal (name / MRN / address / raw calendar date).
- Materialize derived values that EXIST after slice 00 only (e.g. `age`,
  `risk_stratum`). This is a THIN tracer bullet.

OUT — do NOT build now (later slices add them):
- eGFR, cd4_cd8_ratio, thaw_count, remaining_ul, episode boundaries, period
  factor, completion_status, or their source models. Leave hooks, not
  implementations.

## Constraints
MUST:
- Keep all 21 existing slice-00 tests passing; ADD tests, never weaken them.
- Subject IDs stay STRINGS (`SCMVR07`); `col_types` in the manifest must make R
  read `"07"` as a string, never the integer `7`.
- One normalized CSV per model, keys intact (R does the joins). No pre-flattened
  wide matrix.
- Plain human-readable CSV. No binary format.
- Validation/refusal logic enforced at the model/command layer, so shell and
  admin paths both honor it.

MUST NOT:
- Emit any calendar date, name, MRN, or address in any output file.
- Touch `.env`, secrets, settings DB credentials, deploy/, or CI config.
- Add a Python dependency without stating why in the plan first.

## DB note — surface, do not silently decide
The card specifies derived values "materialized via Postgres views", but
`subay/settings.py` defaults `DATABASE_URL` to **sqlite**. Before implementing
view-based materialization, decide and STATE in the plan: run tests against
Postgres (`DATABASE_URL=postgres://...`), or compute derived values in the
command for the sqlite default. If a Postgres-only feature cannot run on the
configured test DB, emit `build.blocked` with the reason rather than quietly
swapping approaches.

## Acceptance criteria (all must pass — binary)
- [ ] Output is a frozen versioned dir `analysis_sets/<version>/`; same DB state
      re-exports to identical per-file SHA-256.
- [ ] One normalized CSV per model, keys intact; no wide matrix.
- [ ] Derived values that exist after slice 00 are materialized once at export.
- [ ] Every date is an integer day-offset from that recipient's `kt_date`; no
      calendar date in any output file.
- [ ] Leak check REFUSES to emit (non-zero exit, nothing written) on any
      name/MRN/address/raw-date; a SEEDED identifier triggers the refusal in a test.
- [ ] `manifest.json` carries per-file row counts, per-file SHA-256, and
      per-column type expectations.
- [ ] CSV is plain and human-readable.

## Approach
Thin slice. Minimum code that satisfies the criteria — no speculative
abstractions, no config knobs, no features beyond the list above. Work
test-first: add a failing test per criterion (including the seeded-identifier
refusal), confirm red, then implement to green.

## Done when
Every acceptance-criteria box is satisfied, `conda run -n subay_env python -m pytest -q` is
fully green (old + new tests), and the Reviewer hat approves. When the Reviewer
approves, print LOOP_COMPLETE.
