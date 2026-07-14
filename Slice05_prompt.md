# Task — SUBAY Slice 05: Viral-load & serology capture

## Context (carry forward)
- Stack: Django + `subay` package, app `subay/registry/`. Validation lives on
  the models. Test harness: `conda run -n subay_env python -m pytest -q`.
- Slices 00–04 are merged and green. Labs attach to the slice 03 visit spine.
- Source of truth: `prd/issues/05-viral-load-serology.md`. Parent spec:
  `prd/CMV-KT_Research_Database_PRD.md`. Read the card before planning.
- The export chokepoint is
  `subay/registry/management/commands/export_analysis_set.py`. Extend it.

## Goal (target state)
The two CMV-status panels the critical-path modules read: the long viral-load
series the episode deriver (slice 07) consumes, and the binary serology the
source-attribution module (slice 11) and risk stratification depend on. A Data
Manager enters both inline under a visit; classification matches the kit exactly,
no equivocal-handling rule.

## Scope
IN — only this slice:
- `CMVQuantitative` stored LONG, one row per result (IU/mL, COBAS 5000,
  LoD = LoQ = 34.5) so repeating measurements aren't forced into a fixed shape.
- `CMVSerology` stored WIDE (IgG value/status, IgM value/status) using the
  LOCKED Snibe Maglumi 600 single 2.0 AU/mL cutoff (≥2.0 positive, <2.0 negative,
  NO equivocal range); numeric AU/mL retained, positive flag DERIVED.
- Recipient pre-KT IgG serostatus (R+/R−) computed ONCE from this assay and
  reused by both Obj 4a stratification and Obj 5 attribution.
- Both models carry the dual-FK "exactly one parent" rule (recipient-visit XOR
  donor).
- Both panels enter the visit→labs admin inlines.
- Extend `export_analysis_set`; serology positive flag + pre-KT serostatus are
  materialized derived values.

OUT — do NOT build now:
- Episode derivation (07), attribution (11), other lab panels (06).

## Constraints
MUST:
- Keep all existing tests passing; ADD tests, never weaken them.
- Derived values are `@property` (computed at read/export), never stored columns.
- Validation/refusal at the model layer (`clean()`/constraints).
- Subject IDs stay STRINGS; never coerce to int.
- `django-simple-history` on new models; admin shows panels as visit inlines.

MUST NOT:
- Store/edit the serology positive flag; no equivocal category.
- Violate the dual-FK exactly-one (recipient-visit XOR donor) constraint.
- Emit any calendar date, name, MRN, or address in any export file (de-id
  chokepoint intact; dates as day-offsets).
- Touch `.env`, secrets, settings DB credentials, `deploy/`, or CI config.
- Add a Python dependency without stating why in the plan first.

## Acceptance criteria (all must pass — binary)
- [ ] `CMVQuantitative` is long, one row per result; readable as an ordered series by the episode deriver.
- [ ] `CMVSerology` is wide; the positive flag derives from the 2.0 AU/mL cutoff with the numeric value retained — no stored/editable positive flag, no equivocal category.
- [ ] Pre-KT IgG serostatus (R+/R−) is computed once and reused by stratification and attribution (internally consistent across objectives).
- [ ] Both models enforce the dual-FK exactly-one (recipient-visit XOR donor) constraint.
- [ ] Both panels enter the visit→labs admin inlines.
- [ ] Both appear in the de-identified export (slice 01); the serology positive flag and pre-KT serostatus are materialized derived values.

## Approach
Thin slice. Minimum code that satisfies the criteria. The 2.0 AU/mL cutoff
derivation and pre-KT serostatus are derived-variable contracts — work test-first
(a failing test per criterion, confirm red, then implement to green).

## Done when
Every acceptance-criteria box is satisfied, the full suite is green
(`conda run -n subay_env python -m pytest -q`, old + new), migrations are clean
(`conda run -n subay_env python manage.py makemigrations --check`), the
backpressure collector exits 0
(`conda run -n subay_env python scripts/backpressure.py`), and the Reviewer hat
approves. When the Reviewer approves, print LOOP_COMPLETE.
