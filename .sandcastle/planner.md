# Planner — SUBAY Slice {{SLICE}}

You PLAN one SUBAY vertical slice. Do NOT write feature or test code.

The slice's issue card is `prd/issues/{{SLICE}}-*.md`. Read it, and read the
parent spec `prd/CMV-KT_Research_Database_PRD.md`.

Read `docs/decisions/DECISIONS.md` — the design rationale for prior slices.
Do NOT contradict a settled decision there; build on it.

First study the existing code so the plan fits reality:
- `subay/registry/models.py`, `validators.py`, `admin.py`
- `subay/registry/management/commands/export_analysis_set.py`
- `subay/registry/tests/` (the prior-art test patterns)

Write a plan to `docs/plans/Slice{{SLICE}}-plan.md` containing:
1. Every acceptance-criteria checkbox from the card, restated as a verifiable check.
2. Ordered TDD steps: which test file each criterion gets, then the
   model / migration / admin / export change that satisfies it.
3. The de-id leak-check assertion this slice must add
   (no calendar date / name / MRN / address in any export file; day-offsets only).
4. Dependencies: confirm blocker slices are already merged; note any model/FK
   this slice attaches to.

If the card is unbuildable now (missing blocker slice, ambiguous spec), stop and
output `<promise>PLAN_BLOCKED</promise>` with a one-line reason.
Otherwise, when the plan file is written, output `<promise>PLAN_READY</promise>`.
