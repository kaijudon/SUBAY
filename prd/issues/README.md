# SUBAY — Tracer-bullet slices (kanban board)

**SUBAY** = **REN**al transplant **O**bservational **V**iral **A**rchive. Django package `subay`.

Sliced from `prd/CMV-KT_Research_Database_PRD.md`. Each `NN-*.md` file is one independently-grabbable **vertical slice** — a thin path through every layer (schema → admin entry → model validation → test → de-identified export), demoable on its own. This is the broader-scope board (full PRD); it extends the parent repo's `SUBAY/issues/` 00–04 set.

Not yet GitHub issues — `renova_final` is not a git repo. To convert: `git init` at project root, add a GitHub remote, then for each file `gh issue create --title "<slice>" --body-file prd/issues/<file>`.

## Board

Columns are folders/state. A card moves to `done/` when its slice merges. Current snapshot:

### 🟢 Ready — no open blockers
- **00** — Walking skeleton & deploy spine

### 📋 Backlog — blocked (transitively on 00)
- **01** — Export / de-id chokepoint · ← 00
- **02** — Recipient & Donor baseline + derived · ← 00
- **03** — Visit spine & closure-shift scheduling · ← 00
- **04** — Completer cohort & replacement · ← 03
- **05** — Viral-load & serology capture · ← 03
- **06** — TBNK / renal / drug-level panels · ← 03
- **07** — CMV episode derivation · ← 05
- **08** — Clinical events · ← 03
- **09** — Biobank ledger · ← 00
- **10** — Genotyping ingest · ← 09
- **11** — Source attribution & concordance · ← 10, 05
- **12** — Resistance surveillance (UL97/UL54) · ← 10
- **13** — Verification gates & roles · ← 05, 07, 10
- **14** — Safety release-timeliness surface · ← 05
- **15** — Production hardening & operations · ← 00

### 🔧 In progress
- (none)

### ✅ Done
- (none — move completed cards into `done/`)

## Dependency order

| # | Slice | Type | Blocked by | Deep module | Stories |
|---|-------|------|-----------|-------------|---------|
| 00 | Walking skeleton & deploy spine | HITL | — | — (spine) | 1,2,66,67,69,70,80 |
| 01 | Export / de-id chokepoint | AFK | 00 | Export / de-id | 73,74,76,77,78,79 |
| 02 | Recipient & Donor baseline + derived | AFK | 00 | — | 3,5,6,7,8,9,10 |
| 03 | Visit spine & closure-shift | AFK | 00 | Visit scheduling | 12–19 |
| 04 | Completer cohort & replacement | AFK | 03 | — | 20,21,22 |
| 05 | Viral-load & serology capture | AFK | 03 | — | 11,23,24,25,27 |
| 06 | TBNK / renal / drug-level panels | AFK | 03 | — | 26,28,29,30 |
| 07 | CMV episode derivation | AFK | 05 | Episode derivation | 37–41 |
| 08 | Clinical events | AFK | 03 | — | 31–36 |
| 09 | Biobank ledger | AFK | 00 | Biobank ledger | 42–48 |
| 10 | Genotyping ingest | AFK | 09 (07 opt.) | Genotyping ingest | 49–57 |
| 11 | Source attribution & concordance | AFK | 10, 05 | — | 58–62 |
| 12 | Resistance surveillance | AFK | 10 | — | 63,64,65 |
| 13 | Verification gates & roles | AFK | 05, 07, 10 | — | 66,67,68 |
| 14 | Safety release-timeliness surface | AFK | 05 | — | 71,72 |
| 15 | Production hardening & operations | HITL | 00 | — | 80–89 |

Graph:
```
00 → {01, 02, 03, 09, 15}
03 → {04, 05, 06, 08}
05 → {07, 11, 14}
09 → 10   (07 optional: CMVEpisode FK)
10 → {11, 12}
{05, 07, 10} → 13
```

After **00** merges, the next parallel wave opens: **01, 02, 03, 09, 15**. Most of the board is AFK; the two HITL cards (**00** scaffold/deploy conventions, **15** physical workstation + DPO/custody sign-off) are the human-checkpoint slices.

## Tracer-bullet note on the export

**01** is built early as a *thin* end-to-end de-identification chokepoint (exports the walking-skeleton subject with day-offsets + manifest + leak-check). Every later data slice (02, 03, 05, 06, 07, 08, 09, 11, 12) then carries an "extend the export + leak-check coverage" acceptance criterion rather than deferring de-id to the end. The privacy boundary is proven on day one and grows with the schema.

## Deferred (settle at implementation time; none block a slice)

Per-locus genotype vocabulary lookup table (needs the ~9-loci allele list); `induction_agent` store-as-column vs derive-from-`MedicationCourse`; suspected vs biopsy-proven rejection inclusion; DOB-vs-age-only minimization (pending IRB); minimal `DonorVisit` final confirmation; aliquot label format (`CMVKT-SUBJID-VISIT-MATRIX-TYPE` on standby); PGC destruction-certificate granularity (per-sample vs per-batch).
