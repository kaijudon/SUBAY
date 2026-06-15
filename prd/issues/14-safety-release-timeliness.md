# Slice 14 — RENOVA: Safety release-timeliness surface

**Type:** AFK
**Deep module:** none (analytics view over existing models + a release-event record)
**User stories:** 71, 72

## Parent

PRD: `prd/CMV-KT_Research_Database_PRD.md`

## What to build

An active safety net so the O4 safety-release SOP has automated detection rather than relying on manual vigilance. A Safety Monitor gets a standing flag the moment a high-viral-load or symptomatic result goes un-actioned past the deadline.

A standing query flags any **QNAT ≥ 10,000 IU/mL or symptomatic flag with no logged release-event within 24h** → flag the Safety Monitor. This reuses the QNAT model (slice 05) plus a lightweight release-event record; it is an analytics view, not heavy new schema. A missed/late release is recorded as a **protocol deviation** and additionally as a **research-related SAE if it caused harm**, so the dual-track safety accounting is reproducible from the data.

## Acceptance criteria

- [ ] A standing query flags QNAT ≥ 10,000 IU/mL (or a symptomatic flag) with no release-event logged within 24h.
- [ ] A release-event logged within 24h clears the flag; the threshold and window are explicit, not hard-coded magic in a view nobody can find.
- [ ] A missed/late release is recordable as a protocol deviation, and as a research-related SAE when it caused harm (dual-track).
- [ ] The flag and the deviation/SAE records are reproducible from stored data (no manual list).
- [ ] Safety records appear in the de-identified export (slice 01) as day-offsets.

## Blocked by

- Blocked by Slice 05 (viral-load capture — the QNAT the flag reads)
