# Planner — SUBAY fix for issue #{{ISSUE}}

You PLAN the fix for ONE GitHub issue filed by the Tester. Do NOT write feature or
test code.

Read the issue — it is your source of truth this round:
    !`gh issue view {{ISSUE}} --json number,title,body,labels`

Read `docs/decisions/DECISIONS.md` — the design rationale for prior slices. Do NOT
contradict a settled decision there; the fix must build on it.

Study the existing code so the plan fits reality:
- `subay/registry/models.py`, `validators.py`, `admin.py`
- `subay/registry/management/commands/` (export + ingest)
- `subay/registry/tests/` (the prior-art test patterns)

Write a plan to `docs/plans/issue-{{ISSUE}}-plan.md` containing:
1. The issue's finding restated as one or more verifiable acceptance checks.
2. Ordered TDD steps: which test file under `subay/registry/tests/` reproduces the
   finding (red), then the model / migration / admin / export-or-ingest change that
   satisfies it (green).
3. Where the fix must live — invariants ON THE MODELS (clean()/constraints), not the
   admin; dates as integer day-offsets only; subject IDs kept as STRINGS.
4. Any de-id leak-check the fix must add, and ordering vs other open issues.

If the issue is unactionable (ambiguous, or fixing it needs a spec decision not in
DECISIONS.md), stop and output `<promise>PLAN_BLOCKED</promise>` with a one-line reason.
Otherwise, when the plan file is written, output `<promise>PLAN_READY</promise>`.
