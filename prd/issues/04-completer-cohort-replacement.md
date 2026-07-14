# Slice 04 — SUBAY: Completer cohort & replacement (D1 + replacement)

**Type:** AFK
**Deep module:** none (cohort-status contract; feeds CONSORT)
**User stories:** 20, 21, 22

## Parent

PRD: `prd/CMV-KT_Research_Database_PRD.md`

## What to build

The completer-cohort accounting that makes the D1-plus-replacement analytic cohort and the CONSORT diagram reproducible from data. A Data Analyst can rebuild the cohort flow without a hand-kept spreadsheet, and a lab error never wrongly evicts a cooperative patient.

Each recipient carries a `completion_status` enum (enrolled / withdrawn / died / lost_to_followup / graft_loss / missed_visit / completed) driving the CONSORT flow. A lab/QC failure is recorded as a **missing observation** at the result level — never a patient-level non-completion — so an external lab error doesn't change `completion_status`. Samples from non-completer subjects stay tracked and still flagged for sequencing inclusion, so the Obj 5 genotype denominator (all sequenced) can legitimately differ from the Obj 1 completer cohort (n=40) per the locked footnote.

## Acceptance criteria

- [ ] `completion_status` is an enum with the seven locked values; it drives a reproducible CONSORT count.
- [ ] A QC/lab failure is recorded as a missing observation on the result, leaving `completion_status` unchanged.
- [ ] A non-completer subject's samples remain queryable and retain a sequencing-inclusion flag.
- [ ] The export (slice 01) exposes `completion_status` and a sequencing-inclusion flag so the n=40 completer cohort and the all-sequenced genotype denominator are both derivable in R.
- [ ] Test: a seeded lab failure does not flip a completed subject to a non-completion status.

## Blocked by

- Blocked by Slice 03 (visit spine — `missed_visit` is set by the closure-shift validator)
