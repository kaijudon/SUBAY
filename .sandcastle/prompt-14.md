# Context

## Recent commits (last 10)

!`git log --oneline -10`

# Task — RENOVA Slice 14: Safety release-timeliness surface

## Context (carry forward)
- Stack: Django + `renova` package, app `renova/registry/`. Validation lives on
  the models. Test harness inside this sandbox: `python -m pytest -q`.
- Slices 00–13 are merged and green. This reuses the QNAT model (slice 05) plus a
  lightweight release-event record; it is an analytics view, not heavy schema.
- Source of truth: `prd/issues/14-safety-release-timeliness.md`. Parent spec:
  `prd/CMV-KT_Research_Database_PRD.md`. Read the card before planning.
- The export chokepoint is
  `renova/registry/management/commands/export_analysis_set.py`. Extend it.

## Goal (target state)
An active safety net so the O4 safety-release SOP has AUTOMATED detection rather
than manual vigilance. A Safety Monitor gets a standing flag the moment a
high-viral-load or symptomatic result goes un-actioned past the deadline.

## Scope
IN — only this slice:
- A standing query flagging any QNAT ≥ 10,000 IU/mL OR symptomatic flag with NO
  logged release-event within 24h → flag the Safety Monitor.
- A lightweight release-event record; a release logged within 24h CLEARS the
  flag. Threshold (10,000) and window (24h) are EXPLICIT named constants, not
  magic buried in a view.
- A missed/late release recordable as a PROTOCOL DEVIATION, and additionally as a
  research-related SAE IF it caused harm (dual-track).
- The flag and deviation/SAE records reproducible from stored data (no manual
  list).
- Safety records in the slice 01 export as day-offsets.

OUT — do NOT build now:
- Notification delivery/transport; only the standing flag + records here.

## Constraints
MUST:
- Keep all existing tests passing; ADD tests, never weaken them.
- Threshold and window are explicit named constants.
- The flag is reproducible from stored data (a query/view), not a manual list.
- Validation at the model layer; subject IDs stay STRINGS;
  `django-simple-history` on the new records.

MUST NOT:
- Hard-code the threshold/window as unfindable magic numbers in a view.
- Conflate the protocol-deviation and SAE tracks.
- Emit any calendar date, name, MRN, or address in any export file (de-id
  chokepoint intact; dates as day-offsets).
- Touch `.env`, secrets, settings DB credentials, `deploy/`, or CI config.
- Add a Python dependency without stating why in the plan first.

## Acceptance criteria (all must pass — binary)
- [ ] A standing query flags QNAT ≥ 10,000 IU/mL (or a symptomatic flag) with no release-event logged within 24h.
- [ ] A release-event logged within 24h clears the flag; the threshold and window are explicit, not hard-coded magic in a view nobody can find.
- [ ] A missed/late release is recordable as a protocol deviation, and as a research-related SAE when it caused harm (dual-track).
- [ ] The flag and the deviation/SAE records are reproducible from stored data (no manual list).
- [ ] Safety records appear in the de-identified export (slice 01) as day-offsets.

## Workflow (RGR — Red → Green → Repeat → Refactor)
1. **Explore** — read `prd/issues/14-safety-release-timeliness.md` and the parent
   PRD. Read the relevant source files and existing tests before any code.
2. **Plan** — decide the smallest change that satisfies the acceptance criteria.
   If a new Python dependency is unavoidable, state why here first.
3. **Execute** — write a failing test first, then the implementation to pass it.
   Build the standing-flag query test-first (≥10,000 un-actioned → flagged;
   release within 24h → cleared) with the threshold/window as named constants.
   Wire the deviation/SAE records and export after.
4. **Verify** — all must pass before committing:
   - `python -m pytest -q` (old + new, full suite green)
   - `python manage.py makemigrations --check` (migrations clean)
   - `python scripts/backpressure.py` (backpressure collector exits 0)
5. **Commit** — a single git commit. The message MUST:
   - Start with `Slice 14:` prefix
   - Name the task and PRD reference (`prd/issues/14-safety-release-timeliness.md`)
   - List key decisions made
   - List files changed

## Rules
- Do not leave commented-out code or TODO comments in committed code.
- Do not weaken or delete existing tests to make the suite pass.
- If blocked (missing context, failing tests you cannot fix), stop and explain
  the blocker rather than committing a partial or broken change.

# Done
When every acceptance-criteria box is satisfied, the full suite is green,
migrations are clean, the backpressure collector exits 0, and the change is
committed — verify each acceptance criterion yourself, then output the completion
signal:

<promise>COMPLETE</promise>
