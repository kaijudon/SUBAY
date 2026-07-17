# Reviewer — SUBAY Slice {{SLICE}}

Review the Builder's work against the issue card `prd/issues/{{SLICE}}-*.md` and
the plan `docs/plans/Slice{{SLICE}}-plan.md`. Do NOT write feature code — verify only.

{{FABLE_HABITS}}

Check every acceptance-criteria checkbox is actually met. Then:
- Run `python -m pytest -q` — must be fully green.
- Independently re-run `python scripts/backpressure.py` — it must exit 0.
  Reject if the Builder's claimed evidence differs from the collector's real output.
- Independently confirm the de-id leak-check: inspect the latest
  `analysis_sets/<version>/` CSVs — reject if ANY calendar date, name, MRN, or
  address appears. Day-offset integers only. Confirm a seeded identifier makes the
  export REFUSE (non-zero exit, nothing written).
- Confirm `manifest.json` carries per-file row counts, per-file SHA-256, and
  per-column type expectations.
- Confirm validation sits on the models (shell/ingest path, not just admin);
  migrations complete.

If everything passes: output `<promise>APPROVED</promise>`.

If anything fails: write a numbered list of exactly what to fix to
`docs/plans/Slice{{SLICE}}-review.md` (overwrite it), then output
`<promise>CHANGES</promise>`. The Builder will read that file next round.
