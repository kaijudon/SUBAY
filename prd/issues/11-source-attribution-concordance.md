# Slice 11 — SUBAY: Source attribution & genotype concordance (Obj 5)

**Type:** AFK (locked decision rules; reviewer enters the graded judgments)
**Deep module:** none (source-attribution priority is a derived-variable contract)
**User stories:** 58, 59, 60, 61, 62

## Parent

PRD: `prd/CMV-KT_Research_Database_PRD.md`

## What to build

The Obj 5 deliverable: a flat source label per subject and a graded per-pair genotype-concordance call, produced under de-identified pair IDs. The attribution priority is computed; the concordance and superinfection judgments are reviewer-set fields with explicit confidence tiers (false precision is recorded *as* indeterminate, not forced to a cutoff).

Each subject is assigned exactly one flat source label by priority (**donor-derived > primary > reactivation**) so the proposal's named three-category deliverable is produced directly. The primary-infection trigger is **QNAT+ alone in an R− recipient** (seroconversion supportive, not gating) so immunosuppression-blunted antibody responses don't false-negative an already near-empty bucket. A per-pair concordance call records: discordant if ≥1 co-resolved locus differs; concordant if all co-resolved agree and ≥2 co-resolved; high-confidence if ≥3 incl ≥1 hypervariable; indeterminate if <2. Mixed-infection donor-derived superinfection is flagged **candidate vs confirmed**. Output is a compact per-pair concordance summary plus a long per-pair × locus allele table (hypervariable-first locus ordering; resistance loci visually separated and labeled "not counted for strain identity").

## Acceptance criteria

- [ ] Each subject gets exactly one flat source label by the locked priority (donor-derived > primary > reactivation).
- [ ] The primary-infection trigger is QNAT+ in an R− recipient; seroconversion is supportive, not gating.
- [ ] The per-pair concordance call implements the graded asymmetric thresholds (discordant / concordant / high-confidence / indeterminate) as specified.
- [ ] Mixed-infection donor-derived superinfection is flagged candidate vs confirmed.
- [ ] Both the compact per-pair summary and the long per-pair × locus allele table export under de-identified pair IDs, hypervariable-first, with resistance loci separated and labeled "not counted for strain identity".
- [ ] The source label and concordance tables appear in the de-identified export (slice 01).

## Blocked by

- Blocked by Slice 10 (genotyping ingest — needs `GenotypeCall` rows)
- Blocked by Slice 05 (viral-load & serology — needs R±/D± serostatus)
