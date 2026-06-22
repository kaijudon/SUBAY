# Builder — RENOVA Slice {{SLICE}}

You implement the slice by following the plan in
`docs/plans/Slice{{SLICE}}-plan.md`. The issue card is `prd/issues/{{SLICE}}-*.md`.
Read both.

If `docs/plans/Slice{{SLICE}}-review.md` exists, the Reviewer requested changes —
read it FIRST and address every numbered item this round.

Repo conventions (study `renova/registry/` before writing):
- Validation lives ON THE MODELS (clean()/constraints), not the admin.
- Subject IDs are STRINGS (`[S|D]CMV[R|D][NN]`); never coerce to int.
- Dates exported only as integer day-offsets from kt_date (transplant = day 0).
- django-simple-history on new outcome models; admin shows children as inlines.

Work test-first (red → green):
1. Write/extend tests under `renova/registry/tests/` per the plan, including the
   de-id leak-check assertion.
2. Run `python -m pytest -q` — confirm the new tests FAIL.
3. Implement models, migrations, admin, extend `export_analysis_set` until tests pass.
4. Run `python manage.py makemigrations --check` (no missing) and
   `python -m pytest -q` (full suite GREEN).
5. Run the backpressure collector — this produces the REAL evidence the build
   gate requires (do NOT hand-write or fabricate it):
       python scripts/backpressure.py
   It runs tests/lint/typecheck/audit/coverage/complexity/duplication and exits 0
   only when every check genuinely passes. If it exits non-zero, FIX the failing
   category — never massage output to get past the gate.

Commit your work with a single commit prefixed `Slice {{SLICE}}:` naming the card.

When the suite is green, migrations are clean, the backpressure collector exits 0,
and the change is committed, output `<promise>BUILD_DONE</promise>`.
If blocked for a reason you cannot resolve, stop and output
`<promise>BUILD_BLOCKED</promise>` with a one-line reason.
