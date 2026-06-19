# Task — RENOVA Slice 06: TBNK / renal / drug-level panels

## Context (carry forward)
- Stack: Django + `renova` package, app `renova/registry/`. Validation lives on
  the models. Test harness: `conda run -n renova_env python -m pytest -q`.
- Slices 00–05 are merged and green. Labs attach to the slice 03 visit spine and
  follow the dual-FK exactly-one pattern established in slice 05.
- Source of truth: `prd/issues/06-tbnk-renal-drug-panels.md`. Parent spec:
  `prd/CMV-KT_Research_Database_PRD.md`. Read the card before planning.
- The export chokepoint is
  `renova/registry/management/commands/export_analysis_set.py`. Extend it.

## Goal (target state)
The remaining measured-every-visit panels, each demonstrating the
wide-vs-long-by-variability rule and the derive-don't-store rule. A Data Manager
enters them inline under a visit; co-drawn subsets stay one row and derived
ratios / eGFR can't drift.

## Scope
IN — only this slice:
- `TBNKPanel` stored WIDE with the seven measured subsets (CD3+, CD3+CD4+,
  CD3+CD8+, CD19+, NK CD3−CD16+CD56+, CD4+CD8+ DP, CD4−CD8− DN), each as absolute
  count (cells/µL) AND % lymphocytes; `cd4_cd8_ratio` DERIVED.
- `RenalFunction` stores raw serum creatinine; `eGFR` DERIVED via CKD-EPI 2021
  (race-free); any lab-reported eGFR is IGNORED; raw creatinine retained.
- `DrugLevel` stores tacrolimus/everolimus troughs LONG, separate from any
  prescription, per-result grain.
- All three enforce the dual-FK exactly-one rule and enter visit→labs inlines.
- Extend `export_analysis_set`; `cd4_cd8_ratio` + `eGFR` materialized derived.

OUT — do NOT build now:
- Prescription/medication-course models (slice 08); `DrugLevel` stays separate.

## Constraints
MUST:
- Keep all existing tests passing; ADD tests, never weaken them.
- Derived values (`cd4_cd8_ratio`, `eGFR`) are `@property`, never stored columns.
- Validation/refusal at the model layer (`clean()`/constraints).
- Subject IDs stay STRINGS; never coerce to int.
- `django-simple-history` on new models; admin shows panels as visit inlines.

MUST NOT:
- Store a derived ratio or eGFR; ignore any lab-reported eGFR.
- Violate the dual-FK exactly-one constraint.
- Emit any calendar date, name, MRN, or address in any export file (de-id
  chokepoint intact; dates as day-offsets).
- Touch `.env`, secrets, settings DB credentials, `deploy/`, or CI config.
- Add a Python dependency without stating why in the plan first.

## Acceptance criteria (all must pass — binary)
- [ ] `TBNKPanel` is one wide row carrying all seven subsets as count + %lymph; `cd4_cd8_ratio` is derived, never stored.
- [ ] `eGFR` is derived from stored creatinine via CKD-EPI 2021 race-free; any lab-reported eGFR is ignored; raw creatinine is retained.
- [ ] `DrugLevel` is long, separate from any prescription model, with a per-result grain.
- [ ] All three enforce the dual-FK exactly-one constraint and appear as visit→labs admin inlines.
- [ ] All three appear in the de-identified export (slice 01) with `cd4_cd8_ratio` and `eGFR` materialized derived.

## Approach
Thin slice. Minimum code that satisfies the criteria. The CKD-EPI 2021 race-free
eGFR and `cd4_cd8_ratio` are derived-variable contracts — work test-first (a
failing test per criterion, confirm red, then implement to green).

## Done when
Every acceptance-criteria box is satisfied, the full suite is green
(`conda run -n renova_env python -m pytest -q`, old + new), migrations are clean
(`conda run -n renova_env python manage.py makemigrations --check`), the
backpressure collector exits 0
(`conda run -n renova_env python scripts/backpressure.py`), and the Reviewer hat
approves. When the Reviewer approves, print LOOP_COMPLETE.
