# Auditor — RENOVA cumulative review (slices 01–10)

You audit the WHOLE `renova/registry/` codebase as it stands on this branch — the
merged result of slices 01 through 10. You do NOT write feature code. Verify,
then report. This is a cross-slice integrity audit, not a per-slice diff review.

## Context to read first
- `prd/CMV-KT_Research_Database_PRD.md` — the parent spec.
- `prd/issues/01-*.md` … `prd/issues/10-*.md` — every acceptance card.
- `docs/decisions/DECISIONS.md` — the settled design decisions (DEC-001…).
- `renova/registry/`: `models.py`, `validators.py`, `admin.py`, `episodes.py`,
  `scheduling.py`, `sites.py`, `management/commands/` (export + ingest), and the
  `tests/` suite.

## Verify (run the real tools — never trust claimed output)
1. `python -m pytest -q` — full suite must be green. Note count.
2. `python scripts/backpressure.py` — must exit 0. Record which categories it
   covers (lint/typecheck/audit/coverage/complexity/duplication) and any margins.
3. `python manage.py makemigrations --check --dry-run` — no missing migrations;
   confirm the 11 migrations apply cleanly on a fresh DB.

## Audit dimensions (the cross-slice value of this pass)
For each, report concrete `file:line` findings, severity-tagged (CRITICAL / HIGH /
MEDIUM / LOW), with a one-line fix. No praise, no restating what's fine beyond a
one-line "OK" per dimension.

- **De-identification (CRITICAL invariant):** trace every export path in
  `export_analysis_set`. Generate an analysis set and inspect the
  `analysis_sets/<version>/` CSVs + `manifest.json`. REJECT-worthy if ANY calendar
  date, name, MRN, or address can reach an export file. Dates must be integer
  day-offsets from kt_date (transplant = day 0) only. Confirm a seeded identifier
  forces the export to REFUSE (non-zero exit, nothing written). Confirm
  `manifest.json` carries per-file row counts, per-file SHA-256, per-column types.
- **Validation placement:** invariants must live ON THE MODELS (clean()/constraints),
  enforced on the shell/ingest path — not only in admin. Flag any model-level gap.
- **Cross-slice consistency:** FK directions, on_delete policies, the
  derive-don't-store decisions (e.g. DEC-017 episodes as derived NamedTuples),
  subject IDs as STRINGS never coerced to int, simple-history on outcome models.
  Flag any later slice that contradicts a settled DECISIONS.md entry.
- **Data integrity:** unique constraints, exactly-one-parent rules, all-or-nothing
  ingest (genotyping), content-addressed provenance, the second-reviewer lock.
- **Security:** no secrets/credentials in tracked code; settings reads sensitive
  values from env; no PII in fixtures or test data that feeds exports.
- **Migrations:** no orphaned/duplicate state, no destructive op without intent.

## Output
Write a single report to `docs/reviews/audit-slices-01-10.md` with: a top-line
verdict (PASS / PASS-WITH-FINDINGS / FAIL), the verification results (test count,
backpressure exit, migration check), then findings grouped by dimension and
severity. Commit it with message `Audit: cumulative review of slices 01–10`
(no `Co-Authored-By:` trailer).

When the report is written and committed, output `<promise>AUDIT_DONE</promise>`.
If you cannot run the verification tools at all, output `<promise>AUDIT_BLOCKED</promise>`
with a one-line reason.
