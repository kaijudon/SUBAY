# Slice 07 — SUBAY: CMV episode derivation

**Type:** AFK
**Deep module:** Episode derivation (test target)
**User stories:** 37, 38, 39, 40, 41

## Parent

PRD: `prd/CMV-KT_Research_Database_PRD.md`

## What to build

A reproducible CMV-episode counter computed from the long viral-load table, applying the locked Topic #4 operational definitions. A Data Analyst never hand-enters episode boundaries — they are derived from raw QNAT results so they reproduce exactly from stored data, and they feed the SAP estimands (proportion / KM / incidence-rate).

A pure function takes a recipient's ordered `CMVQuantitative` result series and returns ordered episodes (start day-offset, end day-offset, index) plus subject-level variables (any-episode-≤6mo boolean, time-to-first-episode + censor flag, episode-count + person-time). Each episode is tagged with a `severity_tier` (asymptomatic / syndrome / disease per Kotton 2018) for the descriptive breakdown **without** that tier branching the pooled primary estimand. Episodes surface via a property/view and flow into the de-identified export (slice 01).

Topic #4 locked rules:
- **Start:** first QNAT ≥ LoD (34.5 IU/mL).
- **End:** first single QNAT < LoD (single-negative, uniform across all severity categories — departs from the Kotton two-negative rule).
- **Recurrence:** every `<LoD → ≥LoD` transition is a new episode; no gap rule.

## Acceptance criteria

- [ ] Episode derivation is a pure function over a result series (no ORM dependency required to test).
- [ ] Start boundary includes the exact value 34.5 (≥ LoD).
- [ ] An episode ends at the first single sub-LoD result (no two-negative requirement).
- [ ] A trajectory fluctuating around LoD is coded as multiple episodes.
- [ ] Every post-resolution positive is counted as a new episode (no gap rule).
- [ ] An all-negative series yields zero episodes.
- [ ] `severity_tier` is recorded per episode and does not alter the pooled episode boundaries.
- [ ] Subject-level "any episode ≤6mo" boolean, time-to-first-episode + censor flag, and episode-count + person-time are produced.
- [ ] Derived episodes (start/end day-offsets, severity, subject-level vars) appear in the de-identified export.

## Blocked by

- Blocked by Slice 05 (viral-load capture — the long `CMVQuantitative` series)
