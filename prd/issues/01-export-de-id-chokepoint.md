# Slice 01 — RENOVA: Export / de-id chokepoint

**Type:** AFK
**Deep module:** Export / de-id (test target)
**User stories:** 73, 74, 76, 77, 78, 79

## Parent

PRD: `prd/CMV-KT_Research_Database_PRD.md`

## What to build

Promote slice 00's minimal export into the single audited de-identification chokepoint. R never touches the live PHI database — it consumes a versioned, frozen, citable snapshot. `export_analysis_set` writes a normalized one-CSV-per-model dataset to `analysis_sets/<version>/`, materializes all derived values once via Postgres views, converts every date to an integer day-offset from the recipient's `kt_date`, confirms no identifier leaked, and writes a `manifest.json` (row counts + per-file SHA-256 + per-column type expectations).

This is the **tracer-bullet privacy boundary**: it ships thin here (exports whatever models exist after slice 00) and every later data slice adds its own CSV + leak-check coverage rather than deferring de-id to the end. End-to-end behavior: a Data Manager runs one command and gets a directory a reviewer can eyeball to confirm no identifier escaped, and that R reads with explicit `col_types` so `"07"` never becomes `7`.

## Acceptance criteria

- [ ] Output is a frozen versioned directory `analysis_sets/<version>/`; re-export to a new version is reproducible (same DB state → same SHA-256 per file).
- [ ] One normalized CSV per model, keys intact (R does the joins); no pre-flattened wide matrix.
- [ ] Derived values materialized once at export via Postgres views — at minimum eGFR (CKD-EPI 2021 race-free), risk_stratum, age, cd4_cd8_ratio, thaw_count, remaining_ul, episode boundaries, four-level period factor, completion_status (each lands as its producing slice merges).
- [ ] Every date is an integer day-offset from that recipient's `kt_date`; no calendar date appears in any output file.
- [ ] Identifier-leak check **refuses to emit** (non-zero exit, nothing written) if any name/MRN/address/raw-date field would appear; a seeded identifier triggers the refusal in test.
- [ ] `manifest.json` carries per-file row counts, per-file SHA-256, and per-column type expectations.
- [ ] Plain human-readable CSV (no binary format).

## Blocked by

- Blocked by Slice 00 (walking skeleton)
