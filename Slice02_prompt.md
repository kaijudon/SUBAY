# Task — SUBAY Slice 02: Recipient & Donor baseline + derived values

## Context (carry forward)
- Stack: Django + `subay` package, app `subay/registry/`. Validation lives on
  the models. Test harness: `conda run -n subay_env python -m pytest -q`
  (pytest-django).
- Slices 00 and 01 are merged and green (29 tests). This slice EXTENDS the
  subject layer from slice 00's stub; it does not rewrite it, and it must keep
  slice 01's de-identified export working.
- Source of truth: `prd/issues/02-recipient-donor-baseline.md`. Parent spec:
  `prd/CMV-KT_Research_Database_PRD.md`. Read the card before planning.
- Subjects live in `subay/registry/models.py` (`BaseSubject`, `Recipient`,
  `Donor`). The export chokepoint is
  `subay/registry/management/commands/export_analysis_set.py`. Extend THOSE —
  do not start over.

## Goal (target state)
The subject layer is the full baseline record with every computable value
*derived, never stored*. A Data Manager enters a recipient's baseline once; age,
risk stratum, and the donor-serostatus reconciliation flag compute on the fly so
stored facts and computed values can never disagree. The donor stays a thin
one-draw record. Recipient + Donor baseline (with derived values materialized,
`kt_date` rendered only as day 0) flow through slice 01's export.

## Scope
IN — only this slice:
- `Recipient(BaseSubject)` gains: `kt_date`, `donor_serostatus` (value clinicians
  acted on at transplant), `has_diabetes` / `has_hypertension` as **three-state
  nullable booleans** (True / False / Unknown), `dialysis_vintage_months`,
  `induction_agent` (atg / basiliximab / none).
- `risk_stratum` as a derived `@property` from current D/R serostatus (Obj 5 D±/R±
  classification). NO stored stratum column.
- `Donor(BaseSubject)` stays thin: type, optional relation, single draw date, at
  most one baseline serology.
- `OtherCondition`: long companion model, one row per non-pre-specified condition.
- A model-level check that **flags** (never auto-overwrites) a mismatch between
  the recipient's recorded `donor_serostatus` and the donor's own serology record.
- Extend `export_analysis_set` so the new baseline + derived values appear in the
  de-identified output.

OUT — do NOT build now (later slices add them):
- Visit spine / closure shift (slice 03), completer cohort (04), viral-load &
  serology timelines (05+), episodes (07), events (08). Leave hooks, not
  implementations. Donor gets NO recipient-grade visit timeline.

## Constraints
MUST:
- Keep all 29 existing tests passing; ADD tests, never weaken them.
- Derived values are `@property` (computed at read/export), never stored columns.
- Three-state nullable booleans: "no diabetes" (False) must be distinguishable
  from "not asked" (None/Unknown), including in the export.
- A donor-serostatus mismatch raises a SURFACED flag for hand reconciliation; the
  system never silently overwrites either value.
- Validation/refusal logic enforced at the model layer (`clean()`/constraints), so
  shell and admin paths both honor it.
- Subject IDs stay STRINGS (`SCMVR07`); never coerce to int.
- `django-simple-history` on new models; admin shows children (e.g.
  `OtherCondition`) as inlines.

MUST NOT:
- Store any derived value (no `risk_stratum` column).
- Use a column-per-possibility for `OtherCondition`; one row per condition.
- Give `Donor` a recipient-grade visit timeline.
- Silently overwrite a donor-serostatus mismatch.
- Emit any calendar date, name, MRN, or address in any export file (slice 01's
  de-id chokepoint stays intact; `kt_date` renders as day 0).
- Touch `.env`, secrets, settings DB credentials, `deploy/`, or CI config.
- Add a Python dependency without stating why in the plan first.

## Acceptance criteria (all must pass — binary)
- [ ] `risk_stratum` is a derived property from current D/R serostatus fields — no
      stored stratum column.
- [ ] `has_diabetes` / `has_hypertension` are three-state nullable booleans; "no
      diabetes" is distinguishable from "not asked" in the export.
- [ ] `dialysis_vintage_months` and `induction_agent` are structured queryable
      fields that can assert absence (`induction_agent = none`).
- [ ] `OtherCondition` stores one row per condition; no column-per-possibility.
- [ ] `Donor` carries at most one baseline serology and a single draw date; no
      recipient-grade visit timeline.
- [ ] A donor-serostatus mismatch raises a surfaced flag for hand reconciliation;
      the system never silently overwrites either value.
- [ ] Recipient + Donor baseline appear in the de-identified export (slice 01)
      with `kt_date` rendered only as day 0 and derived values materialized.

## Approach
Thin slice. Minimum code that satisfies the criteria — no speculative
abstractions, no config knobs, no features beyond the list above. The derived
values (`age`, `risk_stratum`, the mismatch flag) are the candidate
"derived-variable" test suite: work test-first (add a failing test per criterion,
confirm red, then implement to green).

## Done when
Every acceptance-criteria box is satisfied, the full suite is green
(`conda run -n subay_env python -m pytest -q`, old + new tests), migrations are
clean (`conda run -n subay_env python manage.py makemigrations --check`), the
backpressure collector exits 0
(`conda run -n subay_env python scripts/backpressure.py`), and the Reviewer hat
approves. When the Reviewer approves, print LOOP_COMPLETE.
