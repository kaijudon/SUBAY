# Task — SUBAY Slice 04: Completer cohort & replacement (D1 + replacement)

## Context (carry forward)
- Stack: Django + `subay` package, app `subay/registry/`. Validation lives on
  the models. Test harness: `conda run -n subay_env python -m pytest -q`.
- Slices 00–03 are merged and green. This slice ADDS completer-cohort accounting
  on top of the subject + visit spine; `missed_visit` is already set by slice
  03's closure-shift validator.
- Source of truth: `prd/issues/04-completer-cohort-replacement.md`. Parent spec:
  `prd/CMV-KT_Research_Database_PRD.md`. Read the card before planning.
- The export chokepoint is
  `subay/registry/management/commands/export_analysis_set.py`. Extend it.

## Goal (target state)
The completer-cohort accounting that makes the D1-plus-replacement analytic
cohort and the CONSORT diagram reproducible from data. A Data Analyst rebuilds
the cohort flow without a hand-kept spreadsheet, and a lab error never wrongly
evicts a cooperative patient.

## Scope
IN — only this slice:
- `completion_status` enum on each recipient with the seven LOCKED values:
  enrolled / withdrawn / died / lost_to_followup / graft_loss / missed_visit /
  completed — driving a reproducible CONSORT count.
- A lab/QC failure recorded as a MISSING OBSERVATION at the result level — never
  a patient-level non-completion; an external lab error does NOT change
  `completion_status`.
- A sequencing-inclusion flag so non-completer subjects' samples stay queryable
  and the Obj 5 genotype denominator (all sequenced) can legitimately differ
  from the Obj 1 completer cohort (n=40).
- Extend `export_analysis_set` to expose `completion_status` + the
  sequencing-inclusion flag so both denominators are derivable in R.

OUT — do NOT build now:
- The genotyping models themselves (slice 10); only the inclusion flag here.

## Constraints
MUST:
- Keep all existing tests passing; ADD tests, never weaken them.
- Validation/refusal at the model layer (`clean()`/constraints).
- Subject IDs stay STRINGS; never coerce to int.
- `django-simple-history` on new/changed models.

MUST NOT:
- Let a QC/lab failure flip a patient's `completion_status`.
- Store any value the system can derive; no calendar date / name / MRN / address
  in any export file (de-id chokepoint intact; dates as day-offsets).
- Touch `.env`, secrets, settings DB credentials, `deploy/`, or CI config.
- Add a Python dependency without stating why in the plan first.

## Acceptance criteria (all must pass — binary)
- [ ] `completion_status` is an enum with the seven locked values; it drives a reproducible CONSORT count.
- [ ] A QC/lab failure is recorded as a missing observation on the result, leaving `completion_status` unchanged.
- [ ] A non-completer subject's samples remain queryable and retain a sequencing-inclusion flag.
- [ ] The export (slice 01) exposes `completion_status` and a sequencing-inclusion flag so the n=40 completer cohort and the all-sequenced genotype denominator are both derivable in R.
- [ ] Test: a seeded lab failure does not flip a completed subject to a non-completion status.

## Approach
Thin slice. Minimum code that satisfies the criteria. Work test-first (a failing
test per criterion, confirm red, then implement to green). The "lab failure does
not flip completion_status" test is the load-bearing one.

## Done when
Every acceptance-criteria box is satisfied, the full suite is green
(`conda run -n subay_env python -m pytest -q`, old + new), migrations are clean
(`conda run -n subay_env python manage.py makemigrations --check`), the
backpressure collector exits 0
(`conda run -n subay_env python scripts/backpressure.py`), and the Reviewer hat
approves. When the Reviewer approves, print LOOP_COMPLETE.
