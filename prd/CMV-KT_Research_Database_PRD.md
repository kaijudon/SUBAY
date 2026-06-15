# PRD — RENOVA: CMV/Kidney-Transplant Research Database

**Name:** **RENOVA** — **REN**al transplant **O**bservational **V**iral **A**rchive. Human-facing display name "RENOVA"; Django project/package `renova`.

**Project:** Host Clinical Status and Characterization of CMV in Kidney Transplant Patients in Region XI (Bad-ang et al., SPMC). DOST-PCHRD code 2023-08-A2-PCHRD-CORE-TB-16258. Implementing agency SPMC; cooperating DDH, PSN-Mindanao, SPAIRI, UP Mindanao Philippine Genome Center (PGC).

**Source of truth:** `cmv_grilling_session.md` — the resolved-decisions record from the `/grill-me` Socratic interrogation of the protocol, SAP, and database design. This PRD synthesizes that session into a product requirement. It is consistent with, and supersedes in breadth, the earlier `CMV-KT_Database_Design_Spec.md` (which captured only the Topic #7 schema branch). Where any wording here disagrees with a locked decision in the session, **the session's resolved decision wins.**

**Architecture boundary (load-bearing, locked in session Q17 + Q39–Q42):** Django is the **system-of-record, the derived-variable engine, and the single de-identification chokepoint.** It is **not** a pipeline orchestrator and **not** a statistics engine. The heavy statistical analysis (mixed-effects models, Kaplan-Meier, Wilson CIs, Mann-Whitney, genotype-concordance inference) runs in **R against the frozen, de-identified export**. RENOVA's job is to capture data, enforce the rules, *derive* the analysis-ready variables (episode boundaries, period factor, completion status, derived volumes/ratios/eGFR/age, source-attribution labels), and ship a clean snapshot. Every "analytics" requirement below is a *derived-variable contract feeding the export*, not an in-app model fit.

**Stack (locked, session O8 + Topic #7-D):** Django + PostgreSQL + django-simple-history + django-otp (TOTP 2FA on all roles) + customized Django admin as the data-entry interface. Files on a LUKS-encrypted volume via `FileField` (not DB blobs). Sensitive columns via pgcrypto. nginx/gunicorn HTTPS over a Unix socket, localhost-only. Self-hosted on an SPMC-sited workstation; centralized SPMC data entry; **zero DDH user accounts**.

---

## Problem Statement

The study Data Manager (the project bioinformatician) must capture, over a 6-month window per recipient, a longitudinal, multi-matrix research dataset for a target of 40 kidney-transplant recipients plus their living donors — clinical labs, CMV viral loads, drug levels, clinical events, a physical biobank of residual aliquots, and a CMV genotyping pipeline — and then hand a clean, de-identified, citable dataset to an R analyst who runs the locked Statistical Analysis Plan.

The data is sensitive personal information under RA 10173 (PH Data Privacy Act), so de-identification is a hard legal requirement registered with the SPMC DPO (IHOMPS), not a nicety. REDCap was explicitly rejected: no off-the-shelf system enforces this study's specific operational definitions — the single-LoD/single-negative/no-gap CMV episode rules (Topic #4), the strict calendar-day visit schedule with a +3-day closure-shift cap (Q5), the D1-plus-replacement completer cohort (Q4), the event-sourced single-use biobank, the Sanger/qPCR reviewer gates, the serostatus-first/genotype-refined source attribution (Obj 5), and the single de-identification chokepoint.

Without a purpose-built system the Data Manager faces: identifier leakage into the analysis set; biobank-volume bookkeeping that drifts out of sync with the physical freezer; derived clinical values (eGFR, age, risk stratum, CD4/CD8 ratio, episode counts) computed inconsistently; an unauditable chain of custody from tube to genotype call; ambiguous timepoint accounting when a visit shifts off a hospital closure day; and silent operational failure on a single-operator, flaky-power workstation in Davao.

## Solution

**RENOVA** — a self-hosted Django webapp that is the **single system-of-record** for the study, built on five recurring design principles (session §"Design principles"): **derive, don't store**; **event-source append-only changes**; **provenance is first-class data**; **human judgment is a field, not an inference**; and **wide-vs-long by variability, with a confounder override**.

From the user's perspective it provides:

- A customized **Django admin** where a small trained SPMC team enters every visit's labs inline under the visit, with validation living on the *models* so every entry path (admin, shell, ingest command) enforces the same rules.
- **Automatic, on-the-fly computation** of every derived clinical value (age from DOB, eGFR via CKD-EPI 2021 race-free from raw creatinine, CD4/CD8 ratio, risk stratum from D/R serostatus) so stored facts and computed values can never disagree.
- A **visit-scheduling spine** that records both the nominal protocol day and the actual draw date, applies the closure-day forward-shift SOP, enforces the strict +3-day cap, and tracks completion status for the D1-plus-replacement cohort and the CONSORT diagram.
- A **CMV-episode deriver** that applies the study's locked operational definitions (Topic #4: start at first QNAT ≥ 34.5 IU/mL; end at first single negative; every post-resolution positive is a new episode, no gap) to the long viral-load table — feeding the proportion / KM / incidence-rate estimands the SAP needs.
- An **event-sourced biobank ledger** where remaining aliquot volume and thaw count are always *derived* from an append-only event log — the ledger cannot lie about history because you only ever add to it — with a hard single-use / no-refreeze guard and a closed tube → thaw → consumption → run → result custody chain.
- A **genotyping module** that records provenance (tube → pipeline run → call) rather than orchestrating tools, with append-only SHA-256-named raw files and mandatory second-reviewer locks before any call is final; plus the **source-attribution and genotype-concordance** fields (Obj 5) and the **UL97/UL54 resistance-surveillance** record (Q11.7).
- A **safety surface**: an automated release-timeliness flag (any QNAT ≥ 10,000 IU/mL or symptomatic flag with no logged release within 24h → flag the Safety Monitor), reusing the QNAT + release-event models.
- A **single audited de-identification chokepoint**: one management command writes a versioned, frozen, de-identified CSV snapshot (calendar dates replaced by integer day-offsets from transplant) with a SHA-256 manifest. **R never touches the live PHI database.**
- **Defense-in-depth deployment** for a single-operator localhost box where the real enemies are silent failure and operational footguns (auto-reboot into a locked disk, un-decryptable backups), not clever attackers.

## User Stories

### Subjects & enrollment

1. As a Data Manager, I want to register a recipient under a pseudonymous subject ID (`[S|D]CMV[R|D][NN]`, e.g. `SCMVR07`), so that the research DB never holds a name, MRN, or address.
2. As a Data Manager, I want the subject ID treated as an opaque string, so that `"07"` is never silently coerced to the number `7`.
3. As a Data Manager, I want to store a recipient's date of birth once as the single source of truth, so that age at any event is derived and can never go stale.
4. As a Data Analyst, I want each recipient's `donor_serostatus` to be the authoritative value clinicians acted on at transplant, so that risk stratification reflects the real clinical decision rather than a later lab record.
5. As a Data Manager, I want the system to flag (never auto-overwrite) a mismatch between the recipient's recorded donor serostatus and the donor's own serology record, so that I can reconcile it by hand.
6. As a Data Analyst, I want pre-specified confounders (`has_diabetes`, `has_hypertension`) stored as three-state nullable booleans (True / False / Unknown), so that I can distinguish "no diabetes" from "not asked."
7. As a Data Analyst, I want `dialysis_vintage_months` and `induction_agent` (atg / basiliximab / none) stored as structured baseline fields, so that the named confounders are queryable and can assert absence.
8. As a Data Manager, I want non-pre-specified past medical history captured one-row-per-condition in `OtherCondition`, so that I don't need a column per possibility.
9. As a Data Manager, I want donors stored as lightweight records (type, optional relation, at most one baseline serology, single draw date), so that the thin one-draw living-donor workflow isn't burdened with recipient-grade timeline machinery.
10. As a Data Analyst, I want the risk stratum derived from D/R serostatus rather than stored, so that it always reflects the current serostatus fields and stays consistent with the Obj 5 D±/R± classification.
11. As a Data Manager, I want the recipient pre-KT IgG serostatus (R+/R−) computed once from the locked serology assay and reused by both Obj 4a stratification and Obj 5 attribution, so that the cohort's serostatus is internally consistent across objectives.

### Visits, scheduling & closure-shift

12. As a Data Manager, I want the six scheduled recipient timepoints (pre-KT, 1wk/day 7, 1mo/day 30, 3mo/day 90, 4mo/day 120, 6mo/day 180) modeled as visits, so that lab measurements attach to a visit as the data spine.
13. As a Data Manager, I want each visit to store both the nominal protocol day (computed from KT date + offset) and the actual draw date, so that scheduled adherence and any shift are both on the record.
14. As a Data Analyst, I want a `timepoint_label` used for joining labs/episodes to timepoints (not the raw actual day), so that the time axis for KM and TBNK trajectories stays clean.
15. As a Data Manager, I want a visit that lands on a recognized hospital/lab closure day to shift forward to the first day on which clinic *and* lab both operate, recorded as closure-shifted with a reason, so that pre-analytical integrity (same-day plasma separation) is preserved without losing the timepoint.
16. As a Data Manager, I want consecutive closure days treated as one stretch with a single forward shift (no backward shift, no partial visits), so that post-KT day-counting stays deterministic and audit-clean.
17. As a Data Manager, I want the system to reject an actual visit date more than +3 calendar days from nominal and force `completion_status = missed_visit`, so that the strict closure-shift cap is enforced by the model, not by memory.
18. As a Data Manager, I want a `closure_reason` (annexed_holiday / emergency_closure / none) and a free-text stretch reference on each shifted visit, so that the hospital-closure annex and emergency-closure clause are traceable per occurrence.
19. As a Data Analyst, I want `shift_days_from_nominal` stored as a derived integer, so that forced-replacement (closure beyond cap) is distinguishable from patient-initiated non-attendance in the CONSORT diagram.

### Completer cohort & replacement (D1 + replacement)

20. As a Data Analyst, I want each recipient to carry a `completion_status` (enrolled / withdrawn / died / lost_to_followup / graft_loss / missed_visit / completed), so that the D1-plus-replacement analytic cohort and the CONSORT flow are reproducible from data.
21. As a Data Analyst, I want a lab/QC failure recorded as a missing observation (not a patient-level non-completion), so that an external lab error never wrongly evicts a cooperative patient from the completer cohort.
22. As a Data Analyst, I want samples from non-completer subjects still tracked and still flagged for sequencing inclusion, so that the Obj 5 genotype denominator (all sequenced) can differ from the Obj 1 completer cohort (n=40) per the locked footnote.

### Clinical labs (measured-every-visit panels)

23. As a developer, I want each lab result to carry an optional FK to a recipient visit **and** an optional FK to a donor with an exactly-one constraint, so that one lab model serves both subject types without a nullable mess.
24. As a Data Manager, I want CMV serology stored wide (IgG value/status, IgM value/status), so that a densely co-measured low-variability panel is one row.
25. As a Data Manager, I want serology classification to use the locked Snibe Maglumi 600 single 2.0 AU/mL cutoff (≥2.0 positive, <2.0 negative, no equivocal range), with the numeric AU/mL value retained and the positive flag derived, so that the binary serostatus matches the kit and needs no equivocal-handling rule.
26. As a Data Manager, I want the TBNK panel stored wide with the seven measured subsets (CD3+, CD3+CD4+, CD3+CD8+, CD19+, NK CD3−CD16+CD56+, CD4+CD8+ DP, CD4−CD8− DN), both absolute count (cells/µL) and % lymphocytes, with `cd4_cd8_ratio` derived, so that the co-drawn flow subsets are one row and the ratio can't drift.
27. As a Data Manager, I want viral loads (IU/mL, COBAS 5000, LoD = LoQ = 34.5) stored long, one row per result, so that unpredictably repeating measurements aren't forced into a fixed shape and the episode deriver can read them.
28. As a Data Analyst, I want eGFR derived from stored creatinine via CKD-EPI 2021 (race-free), with any lab-reported eGFR ignored, so that no site-equation step-artifact appears at a site-cross in a trajectory.
29. As a Data Analyst, I want raw serum creatinine retained alongside derived eGFR, so that the renal-PK context for valganciclovir dose-reduction (Obj 6) is available, not just the graft-function number.
30. As a Data Analyst, I want tacrolimus/everolimus troughs stored long in `DrugLevel` separate from the prescription, so that the real drug-exposure variable is analyzable on its own grain and can mark "tac target-lowering = CMV management."

### Clinical events

31. As a Data Manager, I want medication courses to carry structured numeric dose (`dose_amount` + `dose_unit` + `frequency`, not free text) and a `drug_class` (antiviral / immunosuppressant), so that doses are queryable and prophylaxis vs treatment intent can be separated.
32. As a Data Analyst, I want antiviral exposure to distinguish prophylaxis (all 40, ~2-month valganciclovir, completed-per-protocol flag, early-discontinuation reason) from treatment escalation (CMV+ subset, agent, duration, dose-reduction count + reason), so that a mandated prophylaxis never masquerades as a clinical response.
33. As a Data Analyst, I want immunosuppression changes classified directionally (reduction-type vs intensification-type) with an optional CMV-management-intent tag, so that bidirectionality (CMV pushes IS down, rejection pushes IS up) is visible rather than averaged to noise.
34. As a Data Analyst, I want rejection episodes modeled as an analytic mirror of CMV episodes (onset_date, rejection_type tcmr/amr/mixed, Banff grade, biopsy_proven flag, biopsy_date, treatment, resolved_date), so that the immunosuppression↔CMV trade-off is analyzable and each IS-up marker is anchored.
35. As a Reviewing Clinician, I want hospitalization CMV/rejection attribution to be reviewer-set nullable FKs with no exactly-one constraint (both may be null), so that "CMV-attributable hospitalization" is a human judgment over Ljungman/Kotton criteria, never auto-inferred from date overlap.
36. As a Data Analyst, I want hospitalizations captured all-cause (admit/discharge/LOS/reason/disposition) with the CMV-attributable subset flagged, so that the denominator makes the attribution honest ("X of Y all-cause episodes met criteria").

### Episode derivation (Topic #4 locked rules)

37. As a Data Analyst, I want a CMV episode to start at the first viral load ≥ LoD (34.5 IU/mL), so that all biologically real DNAemia is captured per the locked definition.
38. As a Data Analyst, I want an episode to end at the first single QNAT result below LoD, applied uniformly to all severity categories, so that the sparse sampling cadence doesn't right-censor episodes at the 6-month endpoint.
39. As a Data Analyst, I want every post-resolution positive (a `<LoD` → `≥LoD` transition) counted as a new episode with no gap rule, so that recurrence counting consistently extends the single-negative philosophy.
40. As a Data Analyst, I want each episode tagged with a `severity_tier` (asymptomatic / syndrome / disease per Kotton 2018) for the descriptive breakdown, without that tier branching the pooled primary estimand.
41. As a Data Analyst, I want the episode counter computed from the long viral-load table rather than hand-entered, so that episode boundaries are reproducible from raw results and feed the subject-level "any episode ≤6mo" boolean, time-to-first-episode + censor flag, and episode-count + person-time variables.

### Biobank ledger

42. As a Biobank custodian, I want each residual tube recorded as a canonical `Aliquot` (the post-clinical-assay leftover, single portion per matrix per timepoint), so that there is one physical record per straw.
43. As a Biobank custodian, I want thaw and consumption recorded as appended events, never edits, so that the ledger cannot lie about history.
44. As a Biobank custodian, I want `remaining_ul` and `thaw_count` derived by summing the event log, so that I never write "this tube now has 0.3 mL" and risk drift from the physical freezer.
45. As a Biobank custodian, I want a DB-level `CHECK volume > 0` plus an application-layer over-consumption guard, so that the system refuses to consume more than exists.
46. As a Biobank custodian, I want single-use / no-refreeze enforced at the DB level, so that residual integrity (≥3 freeze-thaw cycles cause ~0.1–0.3 log10 QNAT drop) is protected.
47. As a Biobank custodian, I want the one sequencing aliquot transferred to PGC tracked separately with a destruction-certificate field (per MOA), so that PGC-held material and SPMC-held residual are distinct in the record.
48. As a Data Analyst, I want every consumption event linked to the pipeline run that consumed it, so that the custody chain from physical tube to analysis is closed.

### Genotyping pipeline (Sanger + qPCR)

49. As a Bioinformatician, I want genotyping results anchored to the source `Aliquot` (not a visit), so that subject and sample-date are derived through the tube and the chain of custody is preserved; with an optional CMV-episode FK enabling within-patient genotype-over-time analysis.
50. As a Bioinformatician, I want a mixed-genotype infection stored as multiple `GenotypeCall` rows (one per allele call, first normal form), so that mixed infections aren't flattened.
51. As a Bioinformatician, I want Sanger loci recorded with the R/F/N taxonomy (Resolved / Failed-QC / No-amplicon) and qPCR loci with per-probe P/N/I rolling up to single / mixed / untyped, so that the locked dual reporting taxonomy is captured exactly.
52. As a Reviewing Clinician, I want raw `.ab1` files append-only and never overwritten, with the human-cleaned consensus attributed to its editor, so that the raw signal is immutable.
53. As a Reviewing Clinician, I want a mandatory second-reviewer lock (`reviewed_by` / `reviewed_at` / `is_locked`) before any genotype call is finalized, so that no call is final without independent review.
54. As a Reviewing Clinician, I want the reviewer gate on qPCR scoped to Inconclusive (`I`) probe readings only, so that clean P/N calls aren't slowed by needless second review.
55. As a Bioinformatician, I want an `ingest_genotyping` command that creates the pipeline-run + result/call/detail rows in a single all-or-nothing transaction, copies files to the encrypted volume, runs integrity checks, and is idempotent, so that re-running never duplicates or half-imports.
56. As a Data Manager, I want each stored file named by its content SHA-256 hash, so that names are self-verifying, deduplicating, and reveal nothing if a file strays from the DB.
57. As a Bioinformatician, I want the frozen GenBank reference accession set (Ross 2020) stored SHA-pinned, so that BLASTn genotype assignment is reproducible against a version-locked reference.

### Source attribution & genotype concordance (Obj 5)

58. As a Data Analyst, I want each subject assigned exactly one flat source label by priority (donor-derived > primary > reactivation), so that the proposal's named three-category deliverable is produced directly.
59. As a Data Analyst, I want the primary-infection trigger to be QNAT+ alone in an R− recipient (seroconversion supportive, not gating), so that immunosuppression-blunted antibody responses don't false-negative an already near-empty bucket.
60. As a Reviewing Clinician, I want a per-pair genotype-concordance call (discordant if ≥1 co-resolved locus differs; concordant if all co-resolved agree and ≥2 co-resolved; high-confidence if ≥3 incl ≥1 hypervariable; indeterminate if <2), so that the graded asymmetric threshold is recorded rather than a false-precision cutoff.
61. As a Reviewing Clinician, I want mixed-infection donor-derived superinfection flagged candidate vs confirmed, so that the only tool that can unmask donor-derived superinfection in the R+/D+ majority is captured with its confidence tier.
62. As a Data Analyst, I want a compact per-pair concordance summary plus a long per-pair × locus allele table (hypervariable-first locus ordering, resistance loci visually separated and labeled "not counted for strain identity"), so that both the reviewer summary and the replication-grade detail are exportable under de-identified pair IDs.

### Resistance surveillance (UL97 / UL54, Q11.7)

63. As a Data Analyst, I want a `ResistanceCall` record (subject, visit, locus UL97/UL54, R/F/N status, variant list, per-variant tier established/polymorphism/unknown, established-resistance-present bool, QNAT IU/mL), so that the curated-list three-tier surveillance and the amplification-floor audit are both supported.
64. As a Data Analyst, I want UL97 and UL54 reported with separate per-locus R-bucket denominators and subject rollup, so that ganciclovir-only (UL97) and cross-resistance (UL54) drug attribution is never pooled away.
65. As a Safety Monitor, I want an established-resistance mutation in a patient with active virological failure flagged for tiered return-of-results (research finding requiring clinical confirmation), so that the locked duty-to-disclose SOP fires on exactly the actionable intersection.

### Access, audit, verification

66. As an Admin, I want roles via Django's built-in Groups/Permissions (`data_manager`, `reviewing_clinician`, `data_analyst`, `admin`), so that PHI access control uses no bespoke security code.
67. As an Admin, I want django-simple-history audit and django-otp TOTP 2FA on all roles, so that audit and access control are built-in, not custom.
68. As a Reviewing Clinician, I want a reusable `VerificationMixin` (`entered_by` / `verified_by` / `verified_at` / `is_verified`, enforcing `entered_by != verified_by`) on outcome-critical fields only (episode adjudication, genotype calls, serostatus, drug levels), so that verification effort is spent only where an error changes a result.
69. As a Data Manager, I want validation to live on the models, so that the admin, the shell, and the ingest command all enforce the same rules.
70. As a Data Manager, I want the data-entry interface to be the customized Django admin (visit→labs inlines, `get_readonly_fields` enforcing `is_locked` and immutable raw files, Group permissions, automatic history), so that a small trained centralized team enters data without a separate forms app to maintain.

### Safety surface (AE/SAE, Q16.3)

71. As a Safety Monitor, I want a standing query that flags any QNAT ≥ 10,000 IU/mL or symptomatic flag with no logged release-event within 24h, so that the O4 safety-release SOP has active detection rather than relying on manual vigilance.
72. As a Safety Monitor, I want a missed/late release recorded as a protocol deviation and additionally as a research-related SAE if it caused harm, so that the dual-track safety accounting is reproducible from the data.

### Analytics export / de-identification

73. As a Data Analyst, I want an `export_analysis_set` command that writes a versioned, frozen, de-identified snapshot to `analysis_sets/<version>/`, so that I analyze a citable dataset and R never touches live PHI.
74. As a Data Analyst, I want derived values (eGFR, risk_stratum, age, cd4_cd8_ratio, thaw_count, remaining_ul, episode index/boundaries, period factor, completion status) materialized once at export via Postgres views, so that R needs no live Python to reproduce them.
75. As a Data Analyst, I want the four-level period factor (pre-KT / post-IS-pre-prophylaxis / on-prophylaxis / post-prophylaxis) derived from timepoint + the study-level 2-month prophylaxis cutoff, so that Obj 4 trajectory and association reporting can group by period without re-deriving it in R.
76. As a Data Analyst, I want one normalized CSV per model with keys intact (R does the joins), so that repeated-measures data isn't forced into a single nonsensical grain.
77. As a DPO/Data Analyst, I want every date converted to an integer day-offset from that recipient's `kt_date` (transplant = day 0) with no calendar dates leaving the export, so that the date-cluster quasi-identifier is removed while clinical intervals are preserved.
78. As a Data Analyst, I want plain human-readable CSV per table plus a `manifest.json` with row counts, per-file SHA-256, and per-column type expectations, so that a reviewer can eyeball the export for leaks and R reads with explicit `col_types` (so `"07"` never coerces to `7`).
79. As a Data Analyst, I want the export to run an identifier-leak check and refuse to emit if any identifier or calendar date is present, so that the de-identification chokepoint is enforced, not merely intended.

### Deployment & operations

80. As an Admin, I want the app bound to `127.0.0.1` only behind nginx-terminated HTTPS (locally-trusted cert) over a Unix socket, so that there's no network attack surface and a clean padlock for the DPO.
81. As an Admin, I want secrets in a root-owned `0600` env file loaded by systemd (never in repo/settings) and pgcrypto as defense-in-depth over off-machine backups, so that off-site encrypted drives are protected even though LUKS is unlocked at runtime.
82. As an Admin, I want key-only SSH (password auth disabled, root login disabled, LAN-bound, fail2ban, UFW inbound 22 from the admin subnet only), so that one hardened remote door exists without the password-brute-force surface.
83. As an Admin, I want a migration wrapper that always `pg_dump`s before `migrate`, applies additive migrations directly, and rehearses destructive/`RunPython` migrations on a scratch DB first, so that ceremony matches data-loss risk.
84. As an Admin, I want auto-installed security updates with operator-gated manual reboots, so that a LUKS box never auto-reboots into a hung passphrase prompt.
85. As an Admin, I want manual LUKS passphrase unlock at console (key only in the operator's head + sealed envelope via Co-DM) paired with a UPS + clean-shutdown daemon, so that at-rest protection is maximal and Postgres is protected from power-loss corruption.
86. As an Admin, I want a three-part backup (Postgres dump + encrypted `MEDIA_ROOT` + secrets incl. pgcrypto key) with the key escrowed on a separate custody path, and a quarterly restore drill that verifies pgcrypto decryption, so that no backup is silently unreadable or missing the genotyping files.
87. As an Admin, I want push-on-failure monitoring (last-backup age, disk %, app health, SSH anomalies) with a dead-man's switch and no PHI in alerts, so that a solo operator's real enemy — silent failure — is caught.
88. As a DPO, I want tamper-evident audit integrity (enforced NTP, Postgres superuser restricted to the Data Manager, periodic history export into immutable off-site backups), so that the single-site RA 10173 posture rests on access control + trustworthy time + a dated prior copy to diff against.
89. As a Co-DM, I want sealed-credentials + off-site Drive 2 custody with a documented bus-factor invocation procedure, so that the system survives a single-operator incident without granting me routine data-entry access.

## Implementation Decisions

**Modules to be built** (green-field; the existing `RENOVA/` skeleton + slices 0–4 are the in-progress reference):

- **Subjects** — abstract `BaseSubject` (no table; `subject_id` / `date_of_birth` / `sex` copied into children at migration); concrete `Recipient(BaseSubject)` (rich, longitudinal) and `Donor(BaseSubject)` (thin, one draw); `OtherCondition` long companion. DOB stored, age / risk_stratum / pre-KT serostatus derived. Confounders wide (three-state nullable booleans), `dialysis_vintage_months`, `induction_agent`. Interface: the Django model layer; data entry via customized admin.
- **Visits, scheduling & closure-shift** — `RecipientVisit` spine storing `nominal_day`, `actual_visit_date`, `timepoint_label`, `closure_shifted` + `closure_reason` (annexed_holiday / emergency_closure / none) + stretch reference, derived `shift_days_from_nominal`; model validator rejecting shift > +3 days and forcing `completion_status = missed_visit`; minimal `DonorVisit` (`donor` + `draw_date`). Deep enough to test (window/cap logic is load-bearing for the time axis).
- **Visits & Labs** — dual-FK "exactly one parent" rule on all lab models (`CMVSerology`, `TBNKPanel`, `CMVQuantitative`, `RenalFunction`, `DrugLevel`). Wide vs long by variability with the confounder override. Serology locked to Snibe Maglumi 600 (2.0 AU/mL binary, numeric value retained, positive flag derived). eGFR / CD4-CD8 / risk derived.
- **Clinical events** — `MedicationCourse` (structured dose, drug_class, prophylaxis/treatment intent), `RejectionEpisode` (Banff vocabulary, biopsy_proven), `Hospitalization` (reviewer-set nullable attribution FKs, no exactly-one constraint), IS-change directional typology.
- **Episode derivation (deep module)** — pure function over the long `CMVQuantitative` series implementing Topic #4: start = first `≥ LoD` (34.5); end = first single `< LoD`; recurrence = every `<LoD → ≥LoD` transition, no gap; severity tier per episode (non-branching). Returns ordered episodes (start day, end day, index) + subject-level booleans/person-time for the SAP estimands. Read-only over stored results.
- **Biobank ledger (deep module)** — `Aliquot` (residual) + `SequencingAliquot` (PGC transfer + destruction cert) + append-only `ThawEvent` / `ConsumptionEvent`; `remaining_ul` / `thaw_count` as derived `@property`; DB `CHECK volume > 0` + app-layer over-consumption guard; DB-level single-use / no-refreeze. `ConsumptionEvent.pipeline_run` FK closes custody. Interface: append-event API + derived read properties; pure and isolatable.
- **Genotyping (deep module for ingest)** — `GenotypingResult` (anchored to `Aliquot`, optional CMVEpisode FK), `GenotypeCall` (long, one row/allele, R/F/N), `SangerDetail` (append-only raw, reviewer lock), `QpcrDetail` + `QpcrProbeReading` (P/N/I, reviewer gate scoped to `call='I'`), `ResistanceCall` (UL97/UL54 three-tier). `ingest_genotyping` management command: single all-or-nothing transaction, copies files to encrypted `MEDIA_ROOT`, integrity checks, idempotent, SHA-256 file naming. SHA-pinned GenBank reference set.
- **Source attribution & concordance** — flat prioritized source label (donor-derived > primary > reactivation), per-pair concordance call (graded/asymmetric), candidate/confirmed superinfection flag, two-tier concordance tables under de-identified pair IDs. Human-judgment fields, not inferred.
- **Access / audit / verification** — Django Groups/Permissions roles; django-simple-history `HistoricalRecords()`; django-otp TOTP; reusable abstract `VerificationMixin` (`entered_by != verified_by`) on outcome-critical fields only. Validation on models.
- **Safety surface** — release-timeliness analytics flag (QNAT ≥ 10,000 / symptomatic without a release-event ≤24h → flag the Safety Monitor); deviation + SAE-if-harm dual-track. Reuses QNAT + release-event models; an analytics view, not new schema.
- **Export / de-id (deep module)** — `export_analysis_set` management command: versioned frozen snapshot dir; Postgres views materialize derived values once (eGFR, age, risk_stratum, cd4_cd8_ratio, thaw_count, remaining_ul, episode boundaries, four-level period factor, completion status); calendar dates → integer day-offsets from `kt_date`; identifier-leak check that refuses to emit on any leak; normalized one-CSV-per-model; `manifest.json` (row counts, per-file SHA-256, per-column types). Pure transform from DB state to a directory of files; isolatable.
- **Deployment / infra** — Topic #7-D D1–D10 + build-time checklist. Not Django-app code per se; codified as systemd units, nginx/gunicorn config, migration wrapper script, backup/monitoring cron, UFW/fail2ban/chrony config.

**Architectural decisions (locked, from session):**

- Django is system-of-record + derived-variable engine + de-id chokepoint; **R runs the statistics** on the frozen export (Q17, Q39–Q42).
- Subject ID is a string primary human-facing key, never numeric; format `[S|D]CMV[R|D][NN]`.
- Identity map lives **outside** the app, on a separate encrypted volume held by SPMC clinical staff; research DB holds pseudonyms only (RA 10173 pseudonymization).
- Derive-don't-store for every computable value (Postgres views mirror the `@property` for export).
- Event-sourced biobank ledger; remaining volume is never mutated; single-use / no-refreeze enforced at the DB layer.
- Strict calendar-day visit schedule; closure-day single forward-shift; +3-day cap enforced by a model validator; both nominal and actual dates recorded.
- D1 + replacement completer cohort; lab failure = missing observation, not non-completion; `completion_status` enum drives CONSORT.
- Human judgment (hospitalization attribution, genotype concordance, source-attribution priority) is a stored reviewer field, never inferred from date overlap.
- Wide vs long decided by variability, with the confounder override (wide even when sparse, to assert absence).
- Serology locked to Snibe Maglumi 600, single 2.0 AU/mL binary cutoff, no equivocal category.
- Django admin is the data-entry interface (customized) — not a custom forms app.
- Single audited de-identification chokepoint; R consumes frozen CSV + manifest only, with explicit column types and integer day-offsets.

**Deferred items (settle at implementation time; none block the schema):** per-locus genotype vocabulary lookup table (needs the ~9-loci allele list); `induction_agent` store-as-column vs derive-from-`MedicationCourse`; suspected vs biopsy-proven rejection inclusion; DOB-vs-age-only minimization (pending IRB); minimal `DonorVisit` final confirmation; aliquot label format (`CMVKT-SUBJID-VISIT-MATRIX-TYPE` on standby); PGC destruction-certificate granularity (per-sample vs per-batch).

## Testing Decisions

**What makes a good test here:** assert external, observable behavior, not implementation details. For these modules the observable behavior is *the value derived from a sequence of stored inputs* — given a series of viral loads, the episodes produced; given a ledger of consumption events, the remaining volume; given a DB state, the contents of the exported files; given a nominal day and a closure calendar, the recorded visit day and completion status. Tests feed inputs through the public interface (append an event, run the export command, call the episode function, save a visit) and assert on outputs (derived properties, file contents, manifest, validation errors), never on private internals. This makes them robust to refactors and exactly the regression net these load-bearing rules need.

**Modules confirmed for tests (the four deep modules, mirroring the existing slices 1–4):**

- **Episode derivation** — table-driven cases over synthetic viral-load series: single episode; episode ending at first single negative (no two-negative requirement); fluctuation around LoD coded as multiple episodes; every post-resolution positive as a new episode (no gap rule); exact `≥ LoD` boundary (34.5 included); all-negative series → zero episodes; outputs reported as episode start/end day-offsets + subject-level "any episode ≤6mo" boolean. Pure function → fast, deterministic, no DB fixtures beyond a result series.
- **Biobank ledger** — append consumption/thaw events and assert derived `remaining_ul` and `thaw_count`; over-consumption rejected by both the DB `CHECK volume > 0` and the app-layer guard; no-refreeze rejected; custody FK (`ConsumptionEvent.pipeline_run`) present after an ingest consumes a tube. Tests exercise the append API and read the derived properties — never write the derived value directly.
- **Export / de-id** — run `export_analysis_set` against a seeded DB and assert: no calendar date appears in any output file (only integer day-offsets from `kt_date`); no identifier field present; the leak check refuses to emit when an identifier is seeded; one CSV per model with keys intact; `manifest.json` row counts and per-file SHA-256 match the written files; per-column type expectations present; re-export to a new version is reproducible. This is the privacy chokepoint — its test is the legal safety net.
- **Genotyping ingest** — run `ingest_genotyping` twice on the same input and assert idempotency (no duplicate `PipelineRun`/result/call rows); a deliberately failing mid-import rolls back the whole transaction (no half-written rows); stored file name equals the input's SHA-256; identical files collapse (dedup); a `GenotypeCall` cannot be finalized without `is_locked` set by a *different* user.

**Additional modules recommended for tests (strong candidates, same deep-module philosophy — confirm before writing):**

- **Visit scheduling & closure-shift** — a visit at +3 days saves as closure-shifted; at +4 days is rejected and forced to `missed_visit`; a multi-day closure stretch produces a single forward shift to the first clinic+lab-operating day; `shift_days_from_nominal` derived correctly. The +3 cap and forward-shift logic are load-bearing for the KM time axis, so they warrant the same test rigor.
- **Derived-variable contracts** — the four-level period factor from timepoint + 2-month cutoff; risk_stratum and pre-KT serostatus from the Snibe Maglumi binary; eGFR from creatinine via CKD-EPI 2021 race-free; source-attribution flat priority (donor-derived > primary > reactivation). These feed the SAP and a silent error changes a published number.

**Prior art:** the existing `RENOVA/` repo (parent project) carries slice issues 00–04 and a `pytest.ini`; establish/extend its conventions — Django `TestCase`/`pytest-django` with `transaction=True` where the all-or-nothing ingest transaction is under test; management-command tests via `call_command` writing to a `tmp_path`; the pure episode-derivation function tested without the ORM. These suites are the prior art for later modules.

## Out of Scope

- The Statistical Analysis Plan modeling itself (Topic #2) — the mixed-effects, KM, Wilson-CI, Mann-Whitney, and concordance *inference* run in **R** on the frozen export; the app only *derives the variables and exports the data* the SAP consumes.
- Protocol-level and governance decisions — cohort, assays, biobank governance, case definitions, consent, IRB/DPO submission text (O1–O8, Topics #1/#3/#4/#6/#9) — separate; this app *records* their outputs, it does not re-decide or author them.
- The identity map (`subject_id` → real patient) — deliberately outside the app, held by SPMC clinical staff on a separate encrypted volume.
- Pipeline orchestration — Django is the system-of-record, not a tool runner; BioEdit / BLASTn / MAFFT run manually, the app records provenance only.
- The R analysis code — R consumes the frozen export; no analysis code lives in this app.
- DDH user accounts / multi-site entry — zero DDH accounts by decision; all entry centralized at SPMC; clinical feedback to DDH flows through the SPMC Project Leader.
- Cloud hosting — explicitly avoided; self-hosted only.
- Figure rendering (KM curves, TBNK spaghetti/LOESS, the Obj 6 swimmer plot) — produced in R from the exported variables; the app supplies the data, not the plots.

## Further Notes

- This PRD is sourced from `cmv_grilling_session.md` (the full grilling record) and is the **broader** companion to `CMV-KT_Database_Design_Spec.md` (Topic #7 schema only) and the prior `RENOVA/CMV-KT_Research_Database_PRD.md` (webapp from the spec). It adds, as first-class requirements, the SAP-driven derived-variable contracts, the visit-window/closure machinery (Q5), source attribution + resistance surveillance (Obj 5), and the safety release-timeliness flag (Q16.3). The heavy design work is already done; the rationale in the session tells you which constraints are load-bearing (de-id chokepoint, event-sourced ledger, reviewer locks, single-LoD episode rules, +3-day cap, derive-don't-store) versus convenience.
- The four deep modules chosen for tests (episode derivation, biobank ledger, export/de-id, genotyping ingest) are exactly the ones where a silent error changes a published result or leaks PHI — hence test-first. The two recommended additions (visit/closure logic, derived-variable contracts) are flagged for confirmation rather than assumed, per the to-prd "check which modules to test" step; default is to write all six.
- Nomenclature: use **Project Leader** / **Co-Project Leader** (DOST-PCHRD convention), never PI / Co-PI, in any user-facing copy.
- Name **RENOVA** (RENal transplant Observational Viral Archive); Django package `renova`; the login page header reads "RENOVA". Use it consistently across PRD, issues, IRB/DPO registration, and `INSTALLED_APPS`.
- Saved at `renova_final/prd/CMV-KT_Research_Database_PRD.md`. No GitHub issue filed — `renova_final` is not a git repo. To file later: `git init` here, add a GitHub remote, then `gh issue create --body-file prd/CMV-KT_Research_Database_PRD.md`.
- Natural next step: `/to-issues` to slice this into independently-grabbable tracer-bullet tickets (the deep modules each make a clean vertical slice; the existing `RENOVA/issues/` 00–04 set is the template to extend with visit-scheduling and source-attribution slices).
