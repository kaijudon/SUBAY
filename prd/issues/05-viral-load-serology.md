# Slice 05 — SUBAY: Viral-load & serology capture

**Type:** AFK
**Deep module:** none (serology cutoff is a derived-variable contract)
**User stories:** 11, 23, 24, 25, 27

## Parent

PRD: `prd/CMV-KT_Research_Database_PRD.md`

## What to build

The two CMV-status panels the critical-path modules read: the long viral-load series the episode deriver (slice 07) consumes, and the binary serology the source-attribution module (slice 11) and risk stratification depend on. A Data Manager enters both inline under a visit; classification matches the kit exactly with no equivocal-handling rule.

Models: `CMVQuantitative` stored **long**, one row per result (IU/mL, COBAS 5000, LoD = LoQ = 34.5), so unpredictably repeating measurements aren't forced into a fixed shape. `CMVSerology` stored **wide** (IgG value/status, IgM value/status) using the locked **Snibe Maglumi 600 single 2.0 AU/mL cutoff** (≥2.0 positive, <2.0 negative, no equivocal range) — the numeric AU/mL value is retained and the positive flag is **derived**. The recipient pre-KT IgG serostatus (R+/R−) is computed once from this assay and reused by both Obj 4a stratification and Obj 5 attribution. Both models carry the dual-FK "exactly one parent" rule.

## Acceptance criteria

- [ ] `CMVQuantitative` is long, one row per result; readable as an ordered series by the episode deriver.
- [ ] `CMVSerology` is wide; the positive flag derives from the 2.0 AU/mL cutoff with the numeric value retained — no stored/editable positive flag, no equivocal category.
- [ ] Pre-KT IgG serostatus (R+/R−) is computed once and reused by stratification and attribution (internally consistent across objectives).
- [ ] Both models enforce the dual-FK exactly-one (recipient-visit XOR donor) constraint.
- [ ] Both panels enter the visit→labs admin inlines.
- [ ] Both appear in the de-identified export (slice 01); the serology positive flag and pre-KT serostatus are materialized derived values.

## Blocked by

- Blocked by Slice 03 (visit spine — labs attach to a visit timepoint)
