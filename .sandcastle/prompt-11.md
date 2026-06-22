# Context

## Recent commits (last 10)

!`git log --oneline -10`

# Task — RENOVA Slice 11: Source attribution & genotype concordance (Obj 5)

## Context (carry forward)
- Stack: Django + `renova` package, app `renova/registry/`. Validation lives on
  the models. Test harness inside this sandbox: `python -m pytest -q`.
- Slices 00–10 are merged and green. This slice needs `GenotypeCall` rows (slice
  10) and R±/D± serostatus (slice 05).
- Source of truth: `prd/issues/11-source-attribution-concordance.md`. Parent
  spec: `prd/CMV-KT_Research_Database_PRD.md`. Read the card before planning.
- The export chokepoint is
  `renova/registry/management/commands/export_analysis_set.py`. Extend it.

## Goal (target state)
The Obj 5 deliverable: a flat source label per subject and a graded per-pair
genotype-concordance call, produced under de-identified pair IDs. The attribution
priority is COMPUTED; the concordance and superinfection judgments are
reviewer-set fields with explicit confidence tiers (false precision recorded AS
indeterminate, not forced to a cutoff).

## Scope
IN — only this slice:
- Exactly one flat source label per subject by LOCKED priority: donor-derived >
  primary > reactivation.
- Primary-infection trigger: QNAT+ alone in an R− recipient (seroconversion
  SUPPORTIVE, not gating).
- Per-pair concordance call: discordant if ≥1 co-resolved locus differs;
  concordant if all co-resolved agree and ≥2 co-resolved; high-confidence if ≥3
  incl ≥1 hypervariable; indeterminate if <2.
- Mixed-infection donor-derived superinfection flagged candidate vs confirmed.
- Output: compact per-pair concordance summary + long per-pair × locus allele
  table (hypervariable-first ordering; resistance loci visually separated and
  labeled "not counted for strain identity").
- Source label + concordance tables in the slice 01 export under de-identified
  pair IDs.

OUT — do NOT build now:
- Resistance surveillance (slice 12); only the visual separation/label here.

## Constraints
MUST:
- Keep all existing tests passing; ADD tests, never weaken them.
- The source label is COMPUTED by the locked priority (not free-entry).
- Reviewer-set concordance/superinfection judgments carry explicit confidence
  tiers; <2 co-resolved → indeterminate, never a forced cutoff.
- Validation at the model layer; subject/pair IDs stay STRINGS.

MUST NOT:
- Gate primary-infection on seroconversion; pool resistance loci into strain
  identity.
- Emit any calendar date, name, MRN, address, or a re-identifying real subject ID
  in any export file (de-id chokepoint intact; de-identified pair IDs only;
  dates as day-offsets).
- Touch `.env`, secrets, settings DB credentials, `deploy/`, or CI config.
- Add a Python dependency without stating why in the plan first.

## Acceptance criteria (all must pass — binary)
- [ ] Each subject gets exactly one flat source label by the locked priority (donor-derived > primary > reactivation).
- [ ] The primary-infection trigger is QNAT+ in an R− recipient; seroconversion is supportive, not gating.
- [ ] The per-pair concordance call implements the graded asymmetric thresholds (discordant / concordant / high-confidence / indeterminate) as specified.
- [ ] Mixed-infection donor-derived superinfection is flagged candidate vs confirmed.
- [ ] Both the compact per-pair summary and the long per-pair × locus allele table export under de-identified pair IDs, hypervariable-first, with resistance loci separated and labeled "not counted for strain identity".
- [ ] The source label and concordance tables appear in the de-identified export (slice 01).

## Workflow (RGR — Red → Green → Repeat → Refactor)
1. **Explore** — read `prd/issues/11-source-attribution-concordance.md` and the
   parent PRD. Read the relevant source files and existing tests before any code.
2. **Plan** — decide the smallest change that satisfies the acceptance criteria.
   If a new Python dependency is unavoidable, state why here first.
3. **Execute** — write a failing test first, then the implementation to pass it.
   Build the computed source-label priority and the graded concordance thresholds
   test-first (priority ordering, R−+QNAT+ → primary, <2 co-resolved →
   indeterminate). Wire export after.
4. **Verify** — all must pass before committing:
   - `python -m pytest -q` (old + new, full suite green)
   - `python manage.py makemigrations --check` (migrations clean)
   - `python scripts/backpressure.py` (backpressure collector exits 0)
5. **Commit** — a single git commit. The message MUST:
   - Start with `Slice 11:` prefix
   - Name the task and PRD reference (`prd/issues/11-source-attribution-concordance.md`)
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
