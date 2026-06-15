# Slice 08 — RENOVA: Clinical events

**Type:** AFK
**Deep module:** none (shallow data models with structured vocabularies)
**User stories:** 31, 32, 33, 34, 35, 36

## Parent

PRD: `prd/CMV-KT_Research_Database_PRD.md`

## What to build

The clinical-event layer that makes the immunosuppression↔CMV trade-off analyzable rather than averaged to noise. A Data Manager records medication courses, rejection episodes, and hospitalizations with structured vocabularies; an Adjudicator sets CMV/rejection attribution by hand — never auto-inferred from date overlap.

Models: `MedicationCourse` with structured numeric dose (`dose_amount` + `dose_unit` + `frequency`, not free text), a `drug_class` (antiviral / immunosuppressant), and the prophylaxis-vs-treatment split (prophylaxis: all 40, ~2-month valganciclovir, completed-per-protocol flag, early-discontinuation reason; treatment escalation: CMV+ subset, agent, duration, dose-reduction count + reason) so a mandated prophylaxis never masquerades as a clinical response. IS changes carry a directional typology (reduction-type vs intensification-type) with an optional CMV-management-intent tag, so bidirectionality is visible. `RejectionEpisode` mirrors the CMV-episode shape (onset_date, rejection_type tcmr/amr/mixed, Banff grade, biopsy_proven flag, biopsy_date, treatment, resolved_date). `Hospitalization` is captured **all-cause** (admit/discharge/LOS/reason/disposition) with **reviewer-set nullable** CMV/rejection attribution FKs (no exactly-one constraint — both may be null), the CMV-attributable subset flagged so the denominator stays honest.

## Acceptance criteria

- [ ] `MedicationCourse` dose is structured numeric (`dose_amount` + `dose_unit` + `frequency`), not free text; `drug_class` separates antiviral from immunosuppressant.
- [ ] Prophylaxis (completed-per-protocol flag, early-discontinuation reason) is distinguishable from treatment escalation (agent, duration, dose-reduction count + reason).
- [ ] IS changes are classified directionally with an optional CMV-management-intent tag.
- [ ] `RejectionEpisode` carries the Banff vocabulary and a `biopsy_proven` flag with `biopsy_date`.
- [ ] `Hospitalization` is all-cause with reviewer-set nullable CMV/rejection attribution FKs (both nullable, no exactly-one); attribution is never auto-inferred from date overlap.
- [ ] All clinical-event models appear in the de-identified export (slice 01) as day-offsets.

## Blocked by

- Blocked by Slice 03 (visit spine — events anchor to the subject timeline)
