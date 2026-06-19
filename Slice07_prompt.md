# Task — RENOVA Slice 07: CMV episode derivation

## Context (carry forward)
- Stack: Django + `renova` package, app `renova/registry/`. Validation lives on
  the models. Test harness: `conda run -n renova_env python -m pytest -q`.
- Slices 00–06 are merged and green. This slice consumes the LONG
  `CMVQuantitative` series from slice 05.
- Source of truth: `prd/issues/07-episode-derivation.md`. Parent spec:
  `prd/CMV-KT_Research_Database_PRD.md`. Read the card before planning.
- The export chokepoint is
  `renova/registry/management/commands/export_analysis_set.py`. Extend it.

## Goal (target state)
A reproducible CMV-episode counter computed from the long viral-load table,
applying the LOCKED Topic #4 operational definitions. A Data Analyst never
hand-enters episode boundaries — they derive from raw QNAT results so they
reproduce exactly from stored data and feed the SAP estimands.

## Scope
IN — only this slice:
- A PURE FUNCTION over a recipient's ordered `CMVQuantitative` series returning
  ordered episodes (start day-offset, end day-offset, index) plus subject-level
  variables: any-episode-≤6mo boolean, time-to-first-episode + censor flag,
  episode-count + person-time.
- Per-episode `severity_tier` (asymptomatic / syndrome / disease per Kotton 2018)
  for the descriptive breakdown WITHOUT branching the pooled primary estimand.
- Surface episodes via a property/view; flow into the slice 01 export.

Topic #4 LOCKED rules:
- Start: first QNAT ≥ LoD (34.5 IU/mL).
- End: first single QNAT < LoD (single-negative, uniform across all severity
  categories — departs from the Kotton two-negative rule).
- Recurrence: every `<LoD → ≥LoD` transition is a new episode; no gap rule.

OUT — do NOT build now:
- Source attribution (11), resistance (12). Episodes only here.

## Constraints
MUST:
- Keep all existing tests passing; ADD tests, never weaken them.
- The deriver is a PURE FUNCTION testable with NO ORM dependency.
- Derived episodes are computed at read/export, never stored as editable columns.
- Subject IDs stay STRINGS; never coerce to int.

MUST NOT:
- Apply a two-negative end rule or any gap rule.
- Let `severity_tier` alter the pooled episode boundaries.
- Emit any calendar date, name, MRN, or address in any export file (de-id
  chokepoint intact; dates as day-offsets).
- Touch `.env`, secrets, settings DB credentials, `deploy/`, or CI config.
- Add a Python dependency without stating why in the plan first.

## Acceptance criteria (all must pass — binary)
- [ ] Episode derivation is a pure function over a result series (no ORM dependency required to test).
- [ ] Start boundary includes the exact value 34.5 (≥ LoD).
- [ ] An episode ends at the first single sub-LoD result (no two-negative requirement).
- [ ] A trajectory fluctuating around LoD is coded as multiple episodes.
- [ ] Every post-resolution positive is counted as a new episode (no gap rule).
- [ ] An all-negative series yields zero episodes.
- [ ] `severity_tier` is recorded per episode and does not alter the pooled episode boundaries.
- [ ] Subject-level "any episode ≤6mo" boolean, time-to-first-episode + censor flag, and episode-count + person-time are produced.
- [ ] Derived episodes (start/end day-offsets, severity, subject-level vars) appear in the de-identified export.

## Approach
Thin slice, but this is a deep-module test target. Build the pure deriver
test-first against hand-built result series (boundary at exactly 34.5, fluctuation
→ multiple episodes, all-negative → zero). Wire ORM/export only after the pure
function is green.

## Done when
Every acceptance-criteria box is satisfied, the full suite is green
(`conda run -n renova_env python -m pytest -q`, old + new), migrations are clean
(`conda run -n renova_env python manage.py makemigrations --check`), the
backpressure collector exits 0
(`conda run -n renova_env python scripts/backpressure.py`), and the Reviewer hat
approves. When the Reviewer approves, print LOOP_COMPLETE.
