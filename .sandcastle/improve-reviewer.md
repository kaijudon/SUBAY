# Reviewer — SUBAY fix for issue #{{ISSUE}}

Review the Builder's work against GitHub issue #{{ISSUE}} and the plan
`docs/plans/issue-{{ISSUE}}-plan.md`. Do NOT write feature code — verify only.
    !`gh issue view {{ISSUE}} --json number,title,body`

Check the issue's finding is actually resolved. Then:
- Run `python -m pytest -q` — must be fully green.
- Independently re-run `python scripts/backpressure.py` — it must exit 0.
  Reject if the Builder's claimed evidence differs from the collector's real output.
- If the finding touched the export path, independently confirm the de-id leak-check:
  inspect the latest `analysis_sets/<version>/` CSVs — reject if ANY calendar date,
  name, MRN, or address appears. Day-offset integers only. Confirm a seeded
  identifier makes the export REFUSE (non-zero exit, nothing written).
- Confirm validation sits on the models (shell/ingest path, not just admin);
  migrations complete.

If everything passes: close the issue and output `<promise>APPROVED</promise>`:
    gh issue close {{ISSUE}} --comment "Fixed and verified by the AFK pipeline."

If anything fails: write a numbered list of exactly what to fix to
`docs/plans/issue-{{ISSUE}}-review.md` (overwrite it), then output
`<promise>CHANGES</promise>`. The Builder will read that file next round. Leave the
issue OPEN.
