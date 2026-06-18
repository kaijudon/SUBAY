# Task — RENOVA Slice 01: Export / de-id chokepoint

Implement the vertical slice specified in:

    prd/issues/01-export-de-id-chokepoint.md

Read that card first; it is the source of truth. Parent spec:
`prd/CMV-KT_Research_Database_PRD.md`. Blocked by Slice 00 (already merged,
21 tests green).

## Goal

Promote slice 00's minimal `export_analysis_set` into the single audited
de-identification chokepoint: a versioned, frozen `analysis_sets/<version>/`
directory — one normalized CSV per model, every date as an integer day-offset
from the recipient's `kt_date`, derived values materialized via Postgres views,
a `manifest.json` (row counts + per-file SHA-256 + per-column type expectations),
and an identifier-leak check that REFUSES to emit (non-zero exit, nothing
written) if any name / MRN / address / raw-date field would appear.

## Done when

Every acceptance-criteria checkbox in the card is met and the Reviewer hat
approves: full suite green via `.venv/bin/python -m pytest -q`, a seeded
identifier triggers the export refusal in test, and the manifest carries
row counts + per-file SHA-256 + per-column type expectations.

When the Reviewer approves, print LOOP_COMPLETE.
