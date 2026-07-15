# Slice 03 — SUBAY: Visit spine & closure-shift scheduling

**Type:** AFK
**Deep module:** Visit scheduling & closure-shift (recommended test target — load-bearing for the KM/TBNK time axis)
**User stories:** 12, 13, 14, 15, 16, 17, 18, 19

## Parent

PRD: `prd/CMV-KT_Research_Database_PRD.md`

## What to build

The visit-scheduling spine that every lab and episode joins to. A Data Manager schedules the six recipient timepoints from `kt_date`; the system records both the nominal protocol day and the actual draw date, applies the hospital/lab closure-day forward-shift SOP, and enforces the strict +3-day cap by a model validator — not by memory.

Model: `RecipientVisit` storing `nominal_day` (computed from `kt_date` + offset for pre-KT / day 7 / 30 / 90 / 120 / 180), `actual_visit_date`, `timepoint_label` (the join key for labs/episodes, **not** the raw actual day), `closure_shifted` bool, `closure_reason` (annexed_holiday / emergency_closure / none) + a free-text stretch reference, and derived `shift_days_from_nominal`. A validator shifts a visit landing on a recognized closure day **forward** to the first day on which clinic *and* lab both operate (consecutive closure days = one stretch, single forward shift, no backward shift, no partial visits), and **rejects** an actual date more than +3 days from nominal, forcing `completion_status = missed_visit`. A minimal `DonorVisit` (`donor` + `draw_date`) covers the thin one-draw donor path.

## Acceptance criteria

- [ ] Six recipient timepoints exist with `nominal_day` computed from `kt_date` + protocol offset.
- [ ] Each visit stores both `nominal_day` and `actual_visit_date`; `timepoint_label` is the lab/episode join key.
- [ ] A visit on a closure day shifts forward to the first clinic+lab-operating day, recorded `closure_shifted` with a `closure_reason` and stretch reference.
- [ ] A multi-day closure stretch produces exactly one forward shift (no backward shift, no partial visit).
- [ ] An actual date > +3 days from nominal is rejected by the model validator and forces `completion_status = missed_visit`.
- [ ] `shift_days_from_nominal` is derived, distinguishing forced-replacement (closure beyond cap) from patient-initiated non-attendance for CONSORT.
- [ ] `DonorVisit` exists as the minimal `donor` + `draw_date` record.
- [ ] Visit fields appear in the de-identified export (slice 01) as day-offsets only.

## Blocked by

- Blocked by Slice 00 (walking skeleton)
