# Slice 12 — RENOVA: Resistance surveillance (UL97 / UL54)

**Type:** AFK
**Deep module:** none (curated-list three-tier rollup)
**User stories:** 63, 64, 65

## Parent

PRD: `prd/CMV-KT_Research_Database_PRD.md`

## What to build

The UL97/UL54 antiviral-resistance surveillance record (Q11.7), kept distinct from strain-identity genotyping so drug attribution is never pooled away, with the duty-to-disclose flag firing on exactly the actionable intersection.

Model: `ResistanceCall` (subject, visit, locus UL97/UL54, R/F/N status, variant list, per-variant tier established / polymorphism / unknown, established-resistance-present bool, QNAT IU/mL at the call) — supporting both the curated-list three-tier surveillance and the amplification-floor audit (QNAT context for why a locus failed to type). UL97 and UL54 are reported with **separate per-locus R-bucket denominators** and a subject rollup, so ganciclovir-only (UL97) and cross-resistance (UL54) attribution stay separable. An established-resistance mutation in a patient with **active virological failure** is flagged for tiered return-of-results (a research finding requiring clinical confirmation), so the locked duty-to-disclose SOP fires only on that intersection.

## Acceptance criteria

- [ ] `ResistanceCall` records locus (UL97/UL54), R/F/N, a variant list with per-variant tier (established / polymorphism / unknown), an established-present bool, and the QNAT at the call.
- [ ] UL97 and UL54 each have their own R-bucket denominator and a subject rollup; the two are never pooled.
- [ ] An established-resistance variant + active virological failure raises the tiered return-of-results flag; an established variant without active failure does not.
- [ ] Resistance calls appear in the de-identified export (slice 01), kept separate from strain-identity loci.

## Blocked by

- Blocked by Slice 10 (genotyping ingest — resistance loci ride the same pipeline-run/result chain)
