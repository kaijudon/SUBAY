# Slice 10 — SUBAY: Genotyping ingest

**Type:** AFK
**Deep module:** Genotyping ingest (test target)
**User stories:** 49, 50, 51, 52, 53, 54, 55, 56, 57

## Parent

PRD: `prd/CMV-KT_Research_Database_PRD.md`

## What to build

The genotyping module records provenance, not orchestration — Django is the system-of-record, BioEdit/BLASTn/MAFFT run manually. A Bioinformatician runs `ingest_genotyping` to load a pipeline run's results; the command is idempotent and all-or-nothing, and no genotype call is final without a second-reviewer lock.

Models: `GenotypingResult` anchored to the source `Aliquot` (subject + sample-date derived through the tube, preserving the slice-09 custody chain; optional CMVEpisode FK enables within-patient genotype-over-time analysis); `GenotypeCall` (long, one row per allele call — a mixed infection is multiple rows, first normal form); Sanger loci recorded with the **R/F/N** taxonomy (Resolved / Failed-QC / No-amplicon) and qPCR loci with per-probe **P/N/I** rolling up to single / mixed / untyped. `SangerDetail` (append-only raw `.ab1`, never overwritten; reviewed consensus attributed to its editor; mandatory `reviewed_by`/`reviewed_at`/`is_locked` gate); `QpcrDetail` + `QpcrProbeReading` repeating group (reviewer gate scoped to `call='I'` only — clean P/N calls aren't slowed). The frozen GenBank reference accession set (Ross 2020) is stored **SHA-pinned** so BLASTn assignment is reproducible.

`ingest_genotyping` management command: creates one `PipelineRun` + result/call/detail rows in a single all-or-nothing transaction; copies files to the encrypted `MEDIA_ROOT` named by content SHA-256; runs integrity checks; idempotent (re-run does not duplicate). `ConsumptionEvent.pipeline_run` (slice 09) now points at the created run.

## Acceptance criteria

- [ ] `GenotypingResult` anchors to an `Aliquot`; subject and sample-date are derived through the tube, not stored on the result; an optional CMVEpisode FK is present.
- [ ] A mixed-genotype infection is stored as multiple `GenotypeCall` rows for the same subject/visit/locus.
- [ ] Sanger loci carry R/F/N; qPCR per-probe P/N/I roll up to single / mixed / untyped.
- [ ] Raw `.ab1` files are append-only, never overwritten; reviewed consensus is attributed to its editor.
- [ ] No `GenotypeCall` is finalized without a second-reviewer lock set by a different user (`entered_by != verified_by`).
- [ ] qPCR reviewer gate applies to `call='I'` rows only; clean P/N calls need no second review.
- [ ] `ingest_genotyping` runs in a single all-or-nothing transaction — a mid-import failure rolls back with no half-written rows.
- [ ] `ingest_genotyping` is idempotent — re-running the same input creates no duplicate `PipelineRun`/result/call rows.
- [ ] Stored file name equals the content SHA-256; identical files collapse (dedup); files land on the encrypted `MEDIA_ROOT`.
- [ ] The Ross 2020 GenBank reference set is stored SHA-pinned.
- [ ] A consumption event from slice 09 links to the created `PipelineRun`, closing tube→analysis custody.

## Blocked by

- Blocked by Slice 09 (biobank ledger — `GenotypingResult` anchors to `Aliquot`; `ConsumptionEvent.pipeline_run`)
- Optional: Slice 07 (episode derivation — for the optional CMVEpisode FK)
