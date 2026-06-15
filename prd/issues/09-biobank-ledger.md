# Slice 09 — RENOVA: Biobank ledger

**Type:** AFK
**Deep module:** Biobank ledger (test target)
**User stories:** 42, 43, 44, 45, 46, 47, 48

## Parent

PRD: `prd/CMV-KT_Research_Database_PRD.md`

## What to build

The biobank as an event-sourced ledger: tube → thaw → consumption. A Biobank custodian records each residual tube as an `Aliquot`, then *appends* thaw and consumption events — never editing a "remaining volume" field. Remaining volume and thaw count are always derived by summing the event log, so the ledger cannot drift from the physical freezer and cannot lie about history. The deep ledger logic needs only an `Aliquot` with a volume, so it can be built and tested independently of the visit spine; the per-timepoint/per-matrix FK attaches opportunistically once slice 03 has merged.

Models: `Aliquot` (canonical physical record, one straw of post-clinical-assay residual, single portion per matrix per timepoint); `SequencingAliquot` (the one aliquot transferred to PGC, with a destruction-certificate field per MOA, kept distinct from SPMC-held residual); `ThawEvent` and `ConsumptionEvent` (append-only). `remaining_ul` and `thaw_count` are derived `@property` (plus Postgres views for export per slice 01), never stored or mutated. DB-level `CHECK volume > 0` plus an application-layer over-consumption guard. Single-use / no-refreeze enforced at the DB level. `ConsumptionEvent.pipeline_run` FK is present to close the custody chain (the FK target lands in slice 10).

## Acceptance criteria

- [ ] `remaining_ul` and `thaw_count` are computed by summing appended events; no stored/mutable remaining-volume column exists.
- [ ] Thaw and consumption are append-only; the admin/API offers no edit or delete of a recorded event.
- [ ] A consumption exceeding remaining volume is rejected by BOTH the DB `CHECK volume > 0` and the application-layer guard.
- [ ] A second thaw that would breach the single-use / no-refreeze rule is rejected at the DB level.
- [ ] `SequencingAliquot` tracks the PGC transfer with a destruction-certificate field, distinct from SPMC-held residual.
- [ ] `ConsumptionEvent` has a nullable `pipeline_run` FK closing the tube→analysis custody chain.
- [ ] Aliquot data is included in the de-identified export (slice 01), with derived volume/thaw_count materialized.

## Blocked by

- Blocked by Slice 00 (walking skeleton)
