# Slice 02 — SUBAY: Recipient & Donor baseline + derived values

**Type:** AFK
**Deep module:** none (derived-variable contracts; candidate for the "derived-variable" test suite)
**User stories:** 3, 5, 6, 7, 8, 9, 10

## Parent

PRD: `prd/CMV-KT_Research_Database_PRD.md`

## What to build

Flesh out the subject layer from slice 00's stub into the full baseline record, with every computable value *derived, never stored*. A Data Manager enters a recipient's baseline once; age, risk stratum, and the donor-serostatus reconciliation flag compute on the fly so stored facts and computed values can never disagree. The donor stays a thin one-draw record.

Models: `Recipient(BaseSubject)` gains `kt_date`, `donor_serostatus` (the value clinicians acted on at transplant), pre-specified confounders `has_diabetes` / `has_hypertension` as **three-state nullable booleans** (True / False / Unknown), `dialysis_vintage_months`, `induction_agent` (atg / basiliximab / none). `Donor(BaseSubject)` is thin (type, optional relation, single draw date, at most one baseline serology). `OtherCondition` is a long companion (one row per non-pre-specified condition). `risk_stratum` is a derived `@property` from D/R serostatus (consistent with the Obj 5 D±/R± classification). A model-level check **flags** (never auto-overwrites) a mismatch between the recipient's recorded `donor_serostatus` and the donor's own serology record.

## Acceptance criteria

- [ ] `risk_stratum` is a derived property from current D/R serostatus fields — no stored stratum column.
- [ ] `has_diabetes` / `has_hypertension` are three-state nullable booleans; "no diabetes" is distinguishable from "not asked" in the export.
- [ ] `dialysis_vintage_months` and `induction_agent` are structured queryable fields that can assert absence (`induction_agent = none`).
- [ ] `OtherCondition` stores one row per condition; no column-per-possibility.
- [ ] `Donor` carries at most one baseline serology and a single draw date; no recipient-grade visit timeline.
- [ ] A donor-serostatus mismatch raises a surfaced flag for hand reconciliation; the system never silently overwrites either value.
- [ ] Recipient + Donor baseline appear in the de-identified export (slice 01) with `kt_date` rendered only as day 0 and derived values materialized.

## Blocked by

- Blocked by Slice 00 (walking skeleton)
