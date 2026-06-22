# Context

## Recent commits (last 10)

!`git log --oneline -10`

# Task — RENOVA Slice 09: Biobank ledger

## Context (carry forward)
- Stack: Django + `renova` package, app `renova/registry/`. Validation lives on
  the models. Test harness inside this sandbox: `python -m pytest -q`.
- Slices 00–08 are merged and green. The deep ledger logic needs only an
  `Aliquot` with a volume, so build/test it independently of the visit spine; the
  per-timepoint/per-matrix FK attaches opportunistically (slice 03 is merged).
- Source of truth: `prd/issues/09-biobank-ledger.md`. Parent spec:
  `prd/CMV-KT_Research_Database_PRD.md`. Read the card before planning.
- The export chokepoint is
  `renova/registry/management/commands/export_analysis_set.py`. Extend it.

## Goal (target state)
The biobank as an event-sourced ledger: tube → thaw → consumption. A Biobank
custodian records each residual tube as an `Aliquot`, then APPENDS thaw and
consumption events — never editing a "remaining volume" field. Remaining volume
and thaw count are always derived by summing the event log, so the ledger cannot
drift from the physical freezer and cannot lie about history.

## Scope
IN — only this slice:
- `Aliquot` (canonical physical record, one straw of post-clinical-assay residual,
  single portion per matrix per timepoint).
- `SequencingAliquot` (the one aliquot transferred to PGC, with a
  destruction-certificate field per MOA, kept distinct from SPMC-held residual).
- `ThawEvent` and `ConsumptionEvent` — APPEND-ONLY.
- `remaining_ul` and `thaw_count` as derived `@property` (plus Postgres views for
  export), never stored or mutated.
- DB-level `CHECK volume > 0` + application-layer over-consumption guard.
- Single-use / no-refreeze enforced at the DB level.
- `ConsumptionEvent.pipeline_run` nullable FK present to close the custody chain
  (FK TARGET lands in slice 10 — nullable hook only here).
- Extend `export_analysis_set` with derived volume/thaw_count materialized.

OUT — do NOT build now:
- The `PipelineRun`/genotyping models (slice 10); only the nullable FK hook here.

## Constraints
MUST:
- Keep all existing tests passing; ADD tests, never weaken them.
- `remaining_ul` / `thaw_count` are computed by summing events, never stored.
- Thaw/consumption are append-only — admin/API offers NO edit or delete.
- Over-consumption rejected by BOTH the DB `CHECK volume > 0` and the app guard.
- No-refreeze enforced at the DB level.
- Subject IDs stay STRINGS; `django-simple-history` on canonical records.

MUST NOT:
- Add a stored/mutable remaining-volume column.
- Allow edit/delete of a recorded event.
- Emit any calendar date, name, MRN, or address in any export file (de-id
  chokepoint intact; dates as day-offsets).
- Touch `.env`, secrets, settings DB credentials, `deploy/`, or CI config.
- Add a Python dependency without stating why in the plan first.

## Acceptance criteria (all must pass — binary)
- [ ] `remaining_ul` and `thaw_count` are computed by summing appended events; no stored/mutable remaining-volume column exists.
- [ ] Thaw and consumption are append-only; the admin/API offers no edit or delete of a recorded event.
- [ ] A consumption exceeding remaining volume is rejected by BOTH the DB `CHECK volume > 0` and the application-layer guard.
- [ ] A second thaw that would breach the single-use / no-refreeze rule is rejected at the DB level.
- [ ] `SequencingAliquot` tracks the PGC transfer with a destruction-certificate field, distinct from SPMC-held residual.
- [ ] `ConsumptionEvent` has a nullable `pipeline_run` FK closing the tube→analysis custody chain.
- [ ] Aliquot data is included in the de-identified export (slice 01), with derived volume/thaw_count materialized.

## Workflow (RGR — Red → Green → Repeat → Refactor)
1. **Explore** — read `prd/issues/09-biobank-ledger.md` and the parent PRD. Read
   the relevant source files and existing tests before writing any code.
2. **Plan** — decide the smallest change that satisfies the acceptance criteria.
   If a new Python dependency is unavoidable, state why here first.
3. **Execute** — write a failing test first, then the implementation to pass it.
   Over-consumption and no-refreeze are the load-bearing tests: assert BOTH the
   DB CHECK and the app guard fire.
4. **Verify** — all must pass before committing:
   - `python -m pytest -q` (old + new, full suite green)
   - `python manage.py makemigrations --check` (migrations clean)
   - `python scripts/backpressure.py` (backpressure collector exits 0)
5. **Commit** — a single git commit. The message MUST:
   - Start with `Slice 09:` prefix
   - Name the task and PRD reference (`prd/issues/09-biobank-ledger.md`)
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
