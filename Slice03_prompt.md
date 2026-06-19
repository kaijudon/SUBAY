# Task — RENOVA Slice 03: Visit spine & closure-shift scheduling

## Context (carry forward)
- Stack: Django + `renova` package, app `renova/registry/`. Validation lives on
  the models. Test harness: `conda run -n renova_env python -m pytest -q`
  (pytest-django).
- Slices 00–02 are merged and green. This slice ADDS the visit-scheduling spine
  every lab and episode later joins to; it does not rewrite the subject layer.
- Source of truth: `prd/issues/03-visit-spine-closure-shift.md`. Parent spec:
  `prd/CMV-KT_Research_Database_PRD.md`. Read the card before planning.
- Subjects live in `renova/registry/models.py`. The export chokepoint is
  `renova/registry/management/commands/export_analysis_set.py`. Extend THOSE.

## Goal (target state)
The visit-scheduling spine. A Data Manager schedules the six recipient
timepoints from `kt_date`; the system records both the nominal protocol day and
the actual draw date, applies the hospital/lab closure-day forward-shift SOP, and
enforces the strict +3-day cap by a model validator — not by memory.

## Scope
IN — only this slice:
- `RecipientVisit`: `nominal_day` (computed from `kt_date` + offset for pre-KT /
  day 7 / 30 / 90 / 120 / 180), `actual_visit_date`, `timepoint_label` (the
  lab/episode join key, NOT the raw actual day), `closure_shifted` bool,
  `closure_reason` (annexed_holiday / emergency_closure / none) + free-text
  stretch reference, derived `shift_days_from_nominal`.
- A validator: a visit on a recognized closure day shifts FORWARD to the first
  day clinic AND lab both operate (consecutive closure days = one stretch, single
  forward shift, no backward shift, no partial visit); an actual date > +3 days
  from nominal is REJECTED and forces `completion_status = missed_visit`.
- `DonorVisit`: minimal `donor` + `draw_date` only.
- Extend `export_analysis_set` so visit fields appear as day-offsets.

OUT — do NOT build now (later slices add them):
- Completer cohort (04), labs/serology (05/06), episodes (07), events (08).
  Leave hooks, not implementations. Donor gets NO recipient-grade timeline.

## Constraints
MUST:
- Keep all existing tests passing; ADD tests, never weaken them.
- Derived values (`nominal_day`, `shift_days_from_nominal`) are computed
  (`@property`/validator output), not free-entry stored facts that can drift.
- Validation/refusal at the model layer (`clean()`/constraints), so shell and
  admin both honor it.
- Subject IDs stay STRINGS; never coerce to int.
- `django-simple-history` on new models; admin shows visits as inlines.

MUST NOT:
- Store a value the system can derive.
- Apply a backward shift, a partial visit, or more than one shift per stretch.
- Give `Donor` a recipient-grade visit timeline.
- Emit any calendar date, name, MRN, or address in any export file (slice 01's
  de-id chokepoint stays intact; dates render as day-offsets from `kt_date`).
- Touch `.env`, secrets, settings DB credentials, `deploy/`, or CI config.
- Add a Python dependency without stating why in the plan first.

## Acceptance criteria (all must pass — binary)
- [ ] Six recipient timepoints exist with `nominal_day` computed from `kt_date` + protocol offset.
- [ ] Each visit stores both `nominal_day` and `actual_visit_date`; `timepoint_label` is the lab/episode join key.
- [ ] A visit on a closure day shifts forward to the first clinic+lab-operating day, recorded `closure_shifted` with a `closure_reason` and stretch reference.
- [ ] A multi-day closure stretch produces exactly one forward shift (no backward shift, no partial visit).
- [ ] An actual date > +3 days from nominal is rejected by the model validator and forces `completion_status = missed_visit`.
- [ ] `shift_days_from_nominal` is derived, distinguishing forced-replacement (closure beyond cap) from patient-initiated non-attendance for CONSORT.
- [ ] `DonorVisit` exists as the minimal `donor` + `draw_date` record.
- [ ] Visit fields appear in the de-identified export (slice 01) as day-offsets only.

## Approach
Thin slice. Minimum code that satisfies the criteria — no speculative
abstractions, no config knobs. The closure-shift validator and
`shift_days_from_nominal` are the candidate deep-module test suite: work
test-first (a failing test per criterion, confirm red, then implement to green).

## Done when
Every acceptance-criteria box is satisfied, the full suite is green
(`conda run -n renova_env python -m pytest -q`, old + new), migrations are clean
(`conda run -n renova_env python manage.py makemigrations --check`), the
backpressure collector exits 0
(`conda run -n renova_env python scripts/backpressure.py`), and the Reviewer hat
approves. When the Reviewer approves, print LOOP_COMPLETE.
