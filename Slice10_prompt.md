# Task — RENOVA Slice 10: Genotyping ingest

## Context (carry forward)
- Stack: Django + `renova` package, app `renova/registry/`. Validation lives on
  the models. Test harness: `conda run -n renova_env python -m pytest -q`.
- Slices 00–09 are merged and green. `GenotypingResult` anchors to the slice 09
  `Aliquot`; `ConsumptionEvent.pipeline_run` (slice 09's nullable hook) now points
  at the created run. Optional CMVEpisode FK uses slice 07.
- Source of truth: `prd/issues/10-genotyping-ingest.md`. Parent spec:
  `prd/CMV-KT_Research_Database_PRD.md`. Read the card before planning.
- The export chokepoint is
  `renova/registry/management/commands/export_analysis_set.py`. Extend it.

## Goal (target state)
The genotyping module records provenance, not orchestration — Django is the
system-of-record; BioEdit/BLASTn/MAFFT run manually. A Bioinformatician runs
`ingest_genotyping` to load a pipeline run's results; the command is idempotent
and all-or-nothing, and no genotype call is final without a second-reviewer lock.

## Scope
IN — only this slice:
- `GenotypingResult` anchored to the source `Aliquot` (subject + sample-date
  DERIVED through the tube, preserving slice 09 custody; optional CMVEpisode FK).
- `GenotypeCall` LONG, one row per allele call (mixed infection = multiple rows).
- Sanger loci with R/F/N (Resolved / Failed-QC / No-amplicon); qPCR per-probe
  P/N/I rolling up to single / mixed / untyped.
- `SangerDetail` (append-only raw `.ab1`, never overwritten; reviewed consensus
  attributed to its editor; mandatory `reviewed_by`/`reviewed_at`/`is_locked`).
- `QpcrDetail` + `QpcrProbeReading` repeating group (reviewer gate scoped to
  `call='I'` ONLY — clean P/N calls aren't slowed).
- Frozen GenBank reference set (Ross 2020) stored SHA-PINNED.
- `ingest_genotyping` command: one `PipelineRun` + result/call/detail rows in a
  SINGLE all-or-nothing transaction; copies files to encrypted `MEDIA_ROOT` named
  by content SHA-256; integrity checks; IDEMPOTENT (re-run no duplicates).
- `ConsumptionEvent.pipeline_run` now points at the created run.
- Extend `export_analysis_set`.

OUT — do NOT build now:
- Source attribution (11), resistance (12) — they ride this pipeline-run chain
  later.

## Constraints
MUST:
- Keep all existing tests passing; ADD tests, never weaken them.
- `ingest_genotyping` is all-or-nothing (single transaction) AND idempotent.
- No `GenotypeCall` finalized without a second-reviewer lock (`entered_by !=
  verified_by`, different user).
- Stored file name == content SHA-256; identical files dedup; encrypted
  `MEDIA_ROOT`.
- Subject IDs stay STRINGS; `django-simple-history` on reviewed models.

MUST NOT:
- Overwrite a raw `.ab1`; store subject/sample-date on the result (derive through
  the tube); slow clean P/N calls with the reviewer gate.
- Emit any calendar date, name, MRN, or address in any export file (de-id
  chokepoint intact; dates as day-offsets).
- Touch `.env`, secrets, settings DB credentials, `deploy/`, or CI config.
- Add a Python dependency without stating why in the plan first.

## Acceptance criteria (all must pass — binary)
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

## Approach
Thin slice, but this is a deep-module test target. Build the transaction
(all-or-nothing + idempotent) and the SHA-named dedup test-first with a seeded
mid-import failure asserting full rollback. Wire the second-reviewer lock and
export after.

## Done when
Every acceptance-criteria box is satisfied, the full suite is green
(`conda run -n renova_env python -m pytest -q`, old + new), migrations are clean
(`conda run -n renova_env python manage.py makemigrations --check`), the
backpressure collector exits 0
(`conda run -n renova_env python scripts/backpressure.py`), and the Reviewer hat
approves. When the Reviewer approves, print LOOP_COMPLETE.
