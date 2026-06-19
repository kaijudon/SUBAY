# Task — RENOVA Slice 08: Clinical events

## Context (carry forward)
- Stack: Django + `renova` package, app `renova/registry/`. Validation lives on
  the models. Test harness: `conda run -n renova_env python -m pytest -q`.
- Slices 00–07 are merged and green. Events anchor to the subject timeline
  (slice 03 visit spine).
- Source of truth: `prd/issues/08-clinical-events.md`. Parent spec:
  `prd/CMV-KT_Research_Database_PRD.md`. Read the card before planning.
- The export chokepoint is
  `renova/registry/management/commands/export_analysis_set.py`. Extend it.

## Goal (target state)
The clinical-event layer that makes the immunosuppression↔CMV trade-off
analyzable rather than averaged to noise. A Data Manager records medication
courses, rejection episodes, and hospitalizations with structured vocabularies; a
Reviewing Clinician sets CMV/rejection attribution BY HAND — never auto-inferred
from date overlap.

## Scope
IN — only this slice:
- `MedicationCourse`: structured numeric dose (`dose_amount` + `dose_unit` +
  `frequency`, NOT free text), `drug_class` (antiviral / immunosuppressant),
  prophylaxis-vs-treatment split (prophylaxis: completed-per-protocol flag,
  early-discontinuation reason; treatment escalation: agent, duration,
  dose-reduction count + reason). IS changes carry a directional typology
  (reduction-type vs intensification-type) + optional CMV-management-intent tag.
- `RejectionEpisode`: onset_date, rejection_type (tcmr/amr/mixed), Banff grade,
  biopsy_proven flag, biopsy_date, treatment, resolved_date.
- `Hospitalization`: ALL-CAUSE (admit/discharge/LOS/reason/disposition) with
  reviewer-set NULLABLE CMV/rejection attribution FKs (both may be null, NO
  exactly-one constraint); CMV-attributable subset flagged.
- Extend `export_analysis_set` (day-offsets).

OUT — do NOT build now:
- Verification mixin / roles (slice 13); attribution is hand-set here, gated
  later.

## Constraints
MUST:
- Keep all existing tests passing; ADD tests, never weaken them.
- Validation/refusal at the model layer (`clean()`/constraints).
- Subject IDs stay STRINGS; never coerce to int.
- `django-simple-history` on new models; admin shows children as inlines.

MUST NOT:
- Use free-text dose; auto-infer CMV/rejection attribution from date overlap;
  put an exactly-one constraint on the hospitalization attribution FKs.
- Emit any calendar date, name, MRN, or address in any export file (de-id
  chokepoint intact; dates as day-offsets).
- Touch `.env`, secrets, settings DB credentials, `deploy/`, or CI config.
- Add a Python dependency without stating why in the plan first.

## Acceptance criteria (all must pass — binary)
- [ ] `MedicationCourse` dose is structured numeric (`dose_amount` + `dose_unit` + `frequency`), not free text; `drug_class` separates antiviral from immunosuppressant.
- [ ] Prophylaxis (completed-per-protocol flag, early-discontinuation reason) is distinguishable from treatment escalation (agent, duration, dose-reduction count + reason).
- [ ] IS changes are classified directionally with an optional CMV-management-intent tag.
- [ ] `RejectionEpisode` carries the Banff vocabulary and a `biopsy_proven` flag with `biopsy_date`.
- [ ] `Hospitalization` is all-cause with reviewer-set nullable CMV/rejection attribution FKs (both nullable, no exactly-one); attribution is never auto-inferred from date overlap.
- [ ] All clinical-event models appear in the de-identified export (slice 01) as day-offsets.

## Approach
Thin slice — shallow data models with structured vocabularies. Work test-first (a
failing test per criterion, confirm red, then implement to green). The "no
auto-inferred attribution" test is the load-bearing one.

## Done when
Every acceptance-criteria box is satisfied, the full suite is green
(`conda run -n renova_env python -m pytest -q`, old + new), migrations are clean
(`conda run -n renova_env python manage.py makemigrations --check`), the
backpressure collector exits 0
(`conda run -n renova_env python scripts/backpressure.py`), and the Reviewer hat
approves. When the Reviewer approves, print LOOP_COMPLETE.
