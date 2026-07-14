# Slice 06 — SUBAY: TBNK / renal / drug-level panels

**Type:** AFK
**Deep module:** none (eGFR + ratio are derived-variable contracts)
**User stories:** 26, 28, 29, 30

## Parent

PRD: `prd/CMV-KT_Research_Database_PRD.md`

## What to build

The remaining measured-every-visit panels, each demonstrating the wide-vs-long-by-variability rule and the derive-don't-store rule. A Data Manager enters them inline under a visit; co-drawn subsets stay one row and derived ratios/eGFR can't drift.

Models: `TBNKPanel` stored **wide** with the seven measured subsets (CD3+, CD3+CD4+, CD3+CD8+, CD19+, NK CD3−CD16+CD56+, CD4+CD8+ DP, CD4−CD8− DN), each as absolute count (cells/µL) **and** % lymphocytes, with `cd4_cd8_ratio` **derived**. `RenalFunction` stores raw serum creatinine; `eGFR` is **derived via CKD-EPI 2021 (race-free)** and any lab-reported eGFR is ignored (so no site-equation step-artifact appears at a site-cross); raw creatinine is retained alongside for the valganciclovir dose-reduction (Obj 6) PK context. `DrugLevel` stores tacrolimus/everolimus troughs **long**, separate from the prescription, so the real drug-exposure variable is analyzable on its own grain. All carry the dual-FK exactly-one rule.

## Acceptance criteria

- [ ] `TBNKPanel` is one wide row carrying all seven subsets as count + %lymph; `cd4_cd8_ratio` is derived, never stored.
- [ ] `eGFR` is derived from stored creatinine via CKD-EPI 2021 race-free; any lab-reported eGFR is ignored; raw creatinine is retained.
- [ ] `DrugLevel` is long, separate from any prescription model, with a per-result grain.
- [ ] All three enforce the dual-FK exactly-one constraint and appear as visit→labs admin inlines.
- [ ] All three appear in the de-identified export (slice 01) with `cd4_cd8_ratio` and `eGFR` materialized derived.

## Blocked by

- Blocked by Slice 03 (visit spine — labs attach to a visit timepoint)
