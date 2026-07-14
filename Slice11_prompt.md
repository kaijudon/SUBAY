# Task — SUBAY Slice 11: Source attribution & genotype concordance (Obj 5)

## Context (carry forward)
- Stack: Django + `subay` package, app `subay/registry/`. Validation lives on
  the models. Test harness: `conda run -n subay_env python -m pytest -q`.
- Slices 00–10 are merged and green. This slice needs `GenotypeCall` rows (slice
  10) and R±/D± serostatus (slice 05).
- Source of truth: `prd/issues/11-source-attribution-concordance.md`. Parent
  spec: `prd/CMV-KT_Research_Database_PRD.md`. Read the card before planning.
- The export chokepoint is
  `subay/registry/management/commands/export_analysis_set.py`. Extend it.

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

## Approach
Thin slice — a derived-variable contract. Build the computed source-label
priority and the graded concordance thresholds test-first (priority ordering,
R−+QNAT+ → primary, <2 co-resolved → indeterminate). Wire export after.

## Done when
Every acceptance-criteria box is satisfied, the full suite is green
(`conda run -n subay_env python -m pytest -q`, old + new), migrations are clean
(`conda run -n subay_env python manage.py makemigrations --check`), the
backpressure collector exits 0
(`conda run -n subay_env python scripts/backpressure.py`), and the Reviewer hat
approves. When the Reviewer approves, print LOOP_COMPLETE.
