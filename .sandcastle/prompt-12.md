# Context

## Recent commits (last 10)

!`git log --oneline -10`

# Task — RENOVA Slice 12: Resistance surveillance (UL97 / UL54)

## Context (carry forward)
- Stack: Django + `renova` package, app `renova/registry/`. Validation lives on
  the models. Test harness inside this sandbox: `python -m pytest -q`.
- Slices 00–11 are merged and green. Resistance loci ride the same
  pipeline-run/result chain as slice 10 genotyping.
- Source of truth: `prd/issues/12-resistance-surveillance.md`. Parent spec:
  `prd/CMV-KT_Research_Database_PRD.md`. Read the card before planning.
- The export chokepoint is
  `renova/registry/management/commands/export_analysis_set.py`. Extend it.

## Goal (target state)
The UL97/UL54 antiviral-resistance surveillance record (Q11.7), kept DISTINCT
from strain-identity genotyping so drug attribution is never pooled away, with the
duty-to-disclose flag firing on exactly the actionable intersection.

## Scope
IN — only this slice:
- `ResistanceCall`: subject, visit, locus (UL97/UL54), R/F/N status, variant
  list, per-variant tier (established / polymorphism / unknown),
  established-resistance-present bool, QNAT IU/mL at the call (supports both the
  curated-list three-tier surveillance and the amplification-floor audit).
- UL97 and UL54 reported with SEPARATE per-locus R-bucket denominators + a
  subject rollup, so ganciclovir-only (UL97) and cross-resistance (UL54)
  attribution stay separable.
- An established-resistance mutation in a patient with ACTIVE virological failure
  flagged for tiered return-of-results; the duty-to-disclose SOP fires ONLY on
  that intersection.
- Resistance calls in the slice 01 export, kept separate from strain-identity
  loci.

OUT — do NOT build now:
- Verification mixin / roles (slice 13); the return-of-results workflow beyond the
  flag.

## Constraints
MUST:
- Keep all existing tests passing; ADD tests, never weaken them.
- UL97 and UL54 each have their OWN R-bucket denominator + subject rollup; never
  pooled.
- The return-of-results flag fires only on established-resistance AND active
  virological failure.
- Validation at the model layer; subject IDs stay STRINGS;
  `django-simple-history` on the call.

MUST NOT:
- Pool UL97/UL54 denominators; fire the duty-to-disclose flag on an established
  variant WITHOUT active failure; mix resistance loci into strain identity.
- Emit any calendar date, name, MRN, or address in any export file (de-id
  chokepoint intact; dates as day-offsets).
- Touch `.env`, secrets, settings DB credentials, `deploy/`, or CI config.
- Add a Python dependency without stating why in the plan first.

## Acceptance criteria (all must pass — binary)
- [ ] `ResistanceCall` records locus (UL97/UL54), R/F/N, a variant list with per-variant tier (established / polymorphism / unknown), an established-present bool, and the QNAT at the call.
- [ ] UL97 and UL54 each have their own R-bucket denominator and a subject rollup; the two are never pooled.
- [ ] An established-resistance variant + active virological failure raises the tiered return-of-results flag; an established variant without active failure does not.
- [ ] Resistance calls appear in the de-identified export (slice 01), kept separate from strain-identity loci.

## Workflow (RGR — Red → Green → Repeat → Refactor)
1. **Explore** — read `prd/issues/12-resistance-surveillance.md` and the parent
   PRD. Read the relevant source files and existing tests before any code.
2. **Plan** — decide the smallest change that satisfies the acceptance criteria.
   If a new Python dependency is unavoidable, state why here first.
3. **Execute** — write a failing test first, then the implementation to pass it.
   Build the per-locus denominators and the duty-to-disclose intersection
   test-first (established+failure → flag; established-only → no flag). Wire
   export after.
4. **Verify** — all must pass before committing:
   - `python -m pytest -q` (old + new, full suite green)
   - `python manage.py makemigrations --check` (migrations clean)
   - `python scripts/backpressure.py` (backpressure collector exits 0)
5. **Commit** — a single git commit. The message MUST:
   - Start with `Slice 12:` prefix
   - Name the task and PRD reference (`prd/issues/12-resistance-surveillance.md`)
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
