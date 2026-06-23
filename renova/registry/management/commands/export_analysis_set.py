"""export_analysis_set — the audited de-identification chokepoint (Slice 01).

Writes one CSV per model to analysis_sets/<version>/, plus a manifest.json
(row counts, per-file SHA-256, per-column type expectations). Every date
becomes an integer day-offset from the recipient's kt_date (transplant =
day 0). No calendar date and no date-of-birth ever leaves. Refuses to
overwrite a frozen version, and refuses to emit at all (nothing written) if
any identifier-shaped value (name/MRN/address/raw calendar date) is found in
the staged output.
"""
import csv
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from renova.registry.attribution import (
    STRAIN_IDENTITY_NOTE,
    counted_for_strain_identity,
    is_resistance,
    locus_order,
)
# Ordered as handle() writes them (recipients → donors → visits → labs).
from renova.registry.models import (
    Recipient,
    Donor,
    RecipientVisit,
    DonorVisit,
    CMVSerology,
    CMVQuantitative,
    OtherCondition,
    TBNKPanel,
    RenalFunction,
    DrugLevel,
    MedicationCourse,
    RejectionEpisode,
    Hospitalization,
    Aliquot,
    GenotypingResult,
    GenotypeCall,
    ConcordancePair,
)

# A bare calendar date should never appear in any output file. Day-offsets are
# bare integers, so they never match. Covers ISO (2020-03-15), slash/dot/dash
# numeric (03/15/2020, 15.03.2020, 3-15-20 — needs two separators, so a lone
# decimal like 3.15 is safe), and written month-name dates (March 15 / 15 Mar).
# This is fail-closed defense-in-depth: a false positive refuses the export for a
# human to inspect, which is the safe direction for a de-id gate.
DATE_RX = re.compile(
    r"\d{4}-\d{2}-\d{2}"
    r"|\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b"
    r"|\b(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2}\b"
    r"|\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\b",
    re.IGNORECASE,
)
# Two consecutive Title-Case words — a plausible person name.
NAME_RX = re.compile(r"\b[A-Z][a-z]+\s[A-Z][a-z]+\b")
# An explicit MRN label followed by digits.
MRN_RX = re.compile(r"MRN[-:\s]?\d+", re.IGNORECASE)
# House number + word + street-suffix.
ADDRESS_RX = re.compile(
    r"\d+\s+\S+\s+(St|Street|Ave|Avenue|Rd|Road|Blvd|Drive|Dr|Lane|Ln)\b", re.IGNORECASE
)

RECIPIENT_COLUMNS = [
    ("subject_id", "c"),
    ("sex", "c"),
    ("age", "i"),
    ("risk_stratum", "c"),
    ("donor_serostatus", "c"),
    ("recipient_serostatus", "c"),
    ("has_diabetes", "c"),
    ("has_hypertension", "c"),
    ("dialysis_vintage_months", "i"),
    ("induction_agent", "c"),
    ("has_donor_serostatus_mismatch", "c"),
    ("donor", "c"),
    ("completion_status", "c"),
    ("sequencing_included", "c"),
    ("pre_kt_igg_serostatus", "c"),  # materialized derived value (Slice 05)
    # Subject-level CMV-episode variables, materialized from cmv_episode_summary
    # (Slice 07). Blank when the recipient has no reported QNAT series.
    ("any_episode_le_6mo", "c"),
    ("time_to_first_episode", "i"),
    ("time_to_first_episode_censored", "c"),
    ("episode_count", "i"),
    ("person_time_days", "i"),
    # Flat source label by the locked priority donor-derived > primary >
    # reactivation (Slice 11, AC1/AC6). Derived @property; blank when no CMV event
    # is attributable. Never stored, so it can't drift from the inputs.
    ("source_label", "c"),
]
# relation (free text, e.g. "sibling") is deliberately NOT exported: an
# unconstrained CharField is a leak vector (a name/date could be typed in), and
# donor_type already carries the analyzable living/deceased signal.
DONOR_COLUMNS = [
    ("subject_id", "c"),
    ("sex", "c"),
    ("donor_type", "c"),
    ("baseline_serostatus", "c"),
]
OTHERCONDITION_COLUMNS = [
    ("id", "i"),
    ("recipient", "c"),
    ("condition", "c"),
    ("present", "c"),
]
VISIT_COLUMNS = [
    ("id", "i"),
    ("recipient", "c"),
    ("timepoint_label", "c"),
    ("nominal_day", "i"),
    ("actual_day_offset", "i"),
    ("closure_shifted", "c"),
    ("closure_reason", "c"),
    ("shift_days_from_nominal", "i"),
    ("completion_status", "c"),
]
# A donor has no kt_date anchor, so draw_date can never become an offset: it is
# blanked entirely (consistent with donor-attached serology, DEC-006). The row
# still lists the draw record without ever emitting the calendar date.
DONORVISIT_COLUMNS = [("id", "i"), ("donor", "c"), ("day_offset", "i")]
SEROLOGY_COLUMNS = [
    ("id", "i"),
    ("parent_type", "c"),
    ("parent_id", "c"),
    ("value", "d"),
    ("is_positive", "c"),
    ("result_status", "c"),
    ("igm_value", "d"),
    ("igm_status", "c"),
    ("igm_positive", "c"),  # materialized derived value (Slice 05)
    ("day_offset", "i"),
]
# Long viral-load series: one row per CMVQuantitative result (Slice 05). A
# donor-attached row blanks day_offset (no kt anchor), mirroring serology.
QUANTITATIVE_COLUMNS = [
    ("id", "i"),
    ("parent_type", "c"),
    ("parent_id", "c"),
    ("value", "d"),
    ("result_status", "c"),
    ("day_offset", "i"),
]
# The seven co-drawn subsets stay one WIDE row; cd4_cd8_ratio is materialized
# derived (never a stored column). Donor-attached rows blank day_offset.
TBNK_SUBSET_FIELDS = [
    "cd3_count", "cd3_pct",
    "cd3_cd4_count", "cd3_cd4_pct",
    "cd3_cd8_count", "cd3_cd8_pct",
    "cd19_count", "cd19_pct",
    "nk_count", "nk_pct",
    "cd4_cd8_dp_count", "cd4_cd8_dp_pct",
    "cd4_cd8_dn_count", "cd4_cd8_dn_pct",
]
TBNK_COLUMNS = (
    [("id", "i"), ("parent_type", "c"), ("parent_id", "c")]
    + [(f, "d") for f in TBNK_SUBSET_FIELDS]
    + [("cd4_cd8_ratio", "d"), ("day_offset", "i")]
)
# Raw creatinine in, eGFR materialized derived out (CKD-EPI 2021). No
# lab-reported eGFR column exists — there is no field to export.
RENAL_COLUMNS = [
    ("id", "i"),
    ("parent_type", "c"),
    ("parent_id", "c"),
    ("serum_creatinine_mg_dl", "d"),
    ("eGFR", "d"),
    ("result_status", "c"),
    ("day_offset", "i"),
]
# Long drug-trough series: one row per result, mirroring CMVQuantitative.
DRUGLEVEL_COLUMNS = [
    ("id", "i"),
    ("parent_type", "c"),
    ("parent_id", "c"),
    ("analyte", "c"),
    ("value", "d"),
    ("result_status", "c"),
    ("day_offset", "i"),
]
# Derived CMV episodes: one row per episode (Slice 07). Boundaries are already
# day-offsets from the deriver — no calendar date can reach this file. Donor QNAT
# has no kt anchor and so produces no episode rows.
EPISODE_COLUMNS = [
    ("recipient", "c"),
    ("episode_index", "i"),
    ("start_day_offset", "i"),
    ("end_day_offset", "i"),  # blank for an open / right-censored episode
    ("severity_tier", "c"),
]


# Recipient-level clinical events (Slice 08). All dates become day-offsets from
# the recipient's kt_date; LOS/duration are integer day-counts (not dates).
# Free-text reasons are deliberately NOT exported (leak vector, mirrors
# RecipientVisit.stretch_reference): dose_reduction_reason is unconstrained text;
# the structured signal (dose_reduction_count, change_direction, course_type,
# disposition enum, and the choice-constrained early_discontinuation_reason)
# carries the analyzable content.
MEDICATIONCOURSE_COLUMNS = [
    ("id", "i"),
    ("recipient", "c"),
    ("drug_class", "c"),
    ("agent", "c"),
    ("dose_amount", "d"),
    ("dose_unit", "c"),
    ("frequency", "c"),
    ("course_type", "c"),
    ("start_day_offset", "i"),
    ("end_day_offset", "i"),
    ("duration_days", "i"),  # derived day-count, never a date
    ("completed_per_protocol", "c"),
    ("early_discontinuation_reason", "c"),  # choice-constrained enum, not free text
    ("dose_reduction_count", "i"),
    ("change_direction", "c"),
    ("cmv_management_intent", "c"),
]
# treatment (free text, e.g. "steroid pulse") is deliberately NOT exported: an
# unconstrained CharField is a leak vector; rejection_type + banff_grade (enums)
# carry the analyzable signal.
REJECTIONEPISODE_COLUMNS = [
    ("id", "i"),
    ("recipient", "c"),
    ("onset_day_offset", "i"),
    ("rejection_type", "c"),
    ("banff_grade", "c"),
    ("biopsy_proven", "c"),
    ("biopsy_day_offset", "i"),
    ("resolved_day_offset", "i"),
]
HOSPITALIZATION_COLUMNS = [
    ("id", "i"),
    ("recipient", "c"),
    ("admit_day_offset", "i"),
    ("discharge_day_offset", "i"),
    ("length_of_stay_days", "i"),  # derived day-count, never a date
    ("disposition", "c"),
    ("cmv_attribution", "c"),  # reviewer-set FK id, or blank
    ("rejection_attribution", "c"),  # reviewer-set FK id, or blank
    ("cmv_attributable", "c"),  # honest-denominator flag (bool3)
]


# Biobank ledger (Slice 09). The straw's collection date becomes a day-offset from
# the recipient's kt_date (blank when the aliquot has no visit anchor — the
# donor/DonorVisit precedent). remaining_ul and thaw_count are materialized from
# the derived @property (summed from the append-only event log), never stored
# columns. The free-text destruction_certificate is NOT exported (leak vector,
# mirroring Hospitalization.reason); thaw/consumption/transfer dates never leave.
ALIQUOT_COLUMNS = [
    ("id", "i"),
    ("recipient", "c"),
    ("matrix", "c"),
    ("collected_day_offset", "i"),
    ("initial_volume_ul", "d"),
    ("remaining_ul", "d"),  # derived, materialized
    ("thaw_count", "i"),  # derived, materialized
]


# Genotyping ingest (Slice 10). subject and sample-date are DERIVED through the
# tube (the slice-09 custody chain); the sample date leaves only as a day-offset
# from the recipient's kt_date (blank when the source aliquot has no visit anchor,
# the donor/aliquot precedent). Deliberately NOT exported (leak vectors): raw
# `.ab1` paths / SHAs / stored file names, consensus sequences, editor/reviewer
# names, and every process timestamp (started_at/completed_at/reviewed_at). The
# qpcr_rollup (single/mixed/untyped) is the materialized derived per-result roll-up.
GENOTYPINGRESULT_COLUMNS = [
    ("id", "i"),
    ("subject", "c"),
    ("assay_type", "c"),
    ("sample_day_offset", "i"),
    ("qpcr_rollup", "c"),  # single/mixed/untyped; blank for a Sanger result
]
GENOTYPECALL_COLUMNS = [
    ("id", "i"),
    ("result", "i"),
    ("locus", "c"),
    ("allele", "c"),
    ("sanger_call", "c"),  # R/F/N; blank for a qPCR-derived call
]


# Source attribution & genotype concordance (Slice 11). The compact per-pair
# summary carries the reviewer's call alongside the DERIVED suggestion + co-resolved
# count (so the grading reproduces from the stored calls) under de-identified pair
# IDs. reviewed_by/reviewed_at (staff attribution) and the raw GenotypingResult pks
# (which would re-expose the sample date through the tube) are NEVER exported — the
# recipient subject_id pseudonym is the only identity that leaves.
CONCORDANCEPAIR_COLUMNS = [
    ("id", "i"),
    ("recipient", "c"),
    ("concordance_call", "c"),  # reviewer-set tier (blank if not yet adjudicated)
    ("suggested_concordance_call", "c"),  # derived from the calls, never stored
    ("co_resolved_count", "i"),
    ("superinfection_status", "c"),
]
# The long per-pair × locus allele table (AC5): one row per pair × locus, ordered
# hypervariable-first → conserved → resistance-last. The resistance loci (UL97,
# UL54) are visually separated by a blank row and carry the literal
# STRAIN_IDENTITY_NOTE so they read as excluded from strain identity. Allele sets
# are the de-identified call codes only (sorted, ";"-joined for a mixed infection).
CONCORDANCELOCUS_COLUMNS = [
    ("pair", "i"),
    ("recipient", "c"),
    ("locus", "c"),
    ("allele_recipient", "c"),
    ("allele_comparator", "c"),
    ("resolved_recipient", "c"),
    ("resolved_comparator", "c"),
    ("counted_for_strain_identity", "c"),
    ("strain_identity_note", "c"),  # STRAIN_IDENTITY_NOTE for resistance loci, else blank
]


def _offset(d, kt_date):
    """Integer days from transplant (day 0). Negative for pre-KT dates."""
    return (d - kt_date).days


def _bool3(v):
    """Three-state bool -> distinguishable cells: True/False/Unknown become
    "true"/"false"/"". Never `v or ""` — that would collapse False to "" and
    lose the "no" vs "not asked" distinction."""
    if v is None:
        return ""
    return "true" if v else "false"


class Command(BaseCommand):
    help = "Write a versioned, de-identified CSV snapshot (dates as day-offsets from kt_date)."

    def add_arguments(self, parser):
        parser.add_argument("version", help="Snapshot version, e.g. v0.1")
        parser.add_argument("--outdir", default="analysis_sets")

    def handle(self, *args, version, outdir, **options):
        outdir_path = Path(outdir)
        base = outdir_path / version
        if base.exists():
            raise CommandError(f"{base} already exists; refusing to overwrite a frozen snapshot.")

        staging = outdir_path / f".{version}.staging-{os.getpid()}"
        staging.mkdir(parents=True)
        try:
            self._write_recipients(staging)
            self._write_donors(staging)
            self._write_visits(staging)
            self._write_donor_visits(staging)
            self._write_serologies(staging)
            self._write_quantitatives(staging)
            self._write_tbnk(staging)
            self._write_renal(staging)
            self._write_druglevels(staging)
            self._write_other_conditions(staging)
            self._write_episodes(staging)
            self._write_medicationcourses(staging)
            self._write_rejectionepisodes(staging)
            self._write_hospitalizations(staging)
            self._write_aliquots(staging)
            self._write_genotyping_results(staging)
            self._write_genotype_calls(staging)
            self._write_concordance_pairs(staging)
            self._write_concordance_loci(staging)
            self._write_manifest(staging, version)
            self._assert_no_identifier_leak(staging)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        staging.rename(base)
        self.stdout.write(self.style.SUCCESS(f"Wrote de-identified snapshot to {base}"))

    @staticmethod
    def _episode_summary_row(s):
        # Subject-level CMV-episode columns; blank when no QNAT series (s is None).
        if s is None:
            return ["", "", "", "", ""]
        return [
            _bool3(s.any_episode_le_6mo),
            s.time_to_first_episode,
            _bool3(s.time_to_first_censored),
            s.episode_count,
            s.person_time,
        ]

    def _write_recipients(self, base):
        with (base / "recipient.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in RECIPIENT_COLUMNS])
            for r in Recipient.objects.order_by("pk"):
                s = r.cmv_episode_summary  # None when no reported QNAT series
                w.writerow(
                    [r.subject_id, r.sex, r.age, r.risk_stratum,
                     r.donor_serostatus or "", r.recipient_serostatus or "",
                     _bool3(r.has_diabetes), _bool3(r.has_hypertension),
                     r.dialysis_vintage_months if r.dialysis_vintage_months is not None else "",
                     r.induction_agent or "",
                     _bool3(r.has_donor_serostatus_mismatch),
                     r.donor_id or "",
                     r.completion_status,
                     _bool3(r.sequencing_included),
                     r.pre_kt_igg_serostatus or ""]
                    + self._episode_summary_row(s)
                    + [r.source_label or ""]
                )

    def _write_donors(self, base):
        with (base / "donor.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in DONOR_COLUMNS])
            for d in Donor.objects.order_by("pk"):
                w.writerow(
                    [d.subject_id, d.sex, d.donor_type or "",
                     d.baseline_serostatus or ""]
                )

    def _write_other_conditions(self, base):
        with (base / "othercondition.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in OTHERCONDITION_COLUMNS])
            for c in OtherCondition.objects.order_by("pk"):
                w.writerow([c.id, c.recipient_id, c.condition, _bool3(c.present)])

    def _write_visits(self, base):
        with (base / "recipientvisit.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in VISIT_COLUMNS])
            for v in RecipientVisit.objects.select_related("recipient").order_by("pk"):
                # All scheduling facts are derived properties (DEC-009); dates
                # only ever leave as integer offsets. stretch_reference is free
                # text and is deliberately NOT exported (leak vector).
                w.writerow([
                    v.id,
                    v.recipient_id,
                    v.timepoint_label,
                    v.nominal_day,
                    _offset(v.actual_visit_date, v.recipient.kt_date),
                    _bool3(v.closure_shifted),
                    v.closure_reason,
                    v.shift_days_from_nominal,
                    v.completion_status,
                ])

    def _write_donor_visits(self, base):
        with (base / "donorvisit.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in DONORVISIT_COLUMNS])
            for v in DonorVisit.objects.order_by("pk"):
                # No kt anchor -> day_offset blank, never the calendar draw_date.
                w.writerow([v.id, v.donor_id, ""])

    def _write_serologies(self, base):
        with (base / "cmvserology.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in SEROLOGY_COLUMNS])
            qs = CMVSerology.objects.select_related("recipient_visit__recipient", "donor").order_by("pk")
            for s in qs:
                if s.recipient_visit_id is not None:
                    parent_type, parent_id = "recipient_visit", s.recipient_visit_id
                    offset = _offset(s.drawn_date, s.recipient_visit.recipient.kt_date)
                else:
                    # No recipient anchor for donor-attached labs in Slice 0.
                    parent_type, parent_id, offset = "donor", s.donor_id, ""
                value_cell = s.value if s.value is not None else ""
                igm_value_cell = s.igm_value if s.igm_value is not None else ""
                igm_positive_cell = "" if s.igm_positive is None else s.igm_positive
                w.writerow([s.id, parent_type, parent_id, value_cell, s.is_positive,
                            s.result_status, igm_value_cell, s.igm_status,
                            igm_positive_cell, offset])

    def _write_quantitatives(self, base):
        with (base / "cmvquantitative.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in QUANTITATIVE_COLUMNS])
            qs = CMVQuantitative.objects.select_related(
                "recipient_visit__recipient", "donor"
            ).order_by("pk")
            for q in qs:
                if q.recipient_visit_id is not None:
                    parent_type, parent_id = "recipient_visit", q.recipient_visit_id
                    offset = _offset(q.drawn_date, q.recipient_visit.recipient.kt_date)
                else:
                    # No kt anchor for donor-attached labs -> blank offset (DEC-006).
                    parent_type, parent_id, offset = "donor", q.donor_id, ""
                value_cell = q.value if q.value is not None else ""
                w.writerow([q.id, parent_type, parent_id, value_cell,
                            q.result_status, offset])

    def _write_tbnk(self, base):
        with (base / "tbnkpanel.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in TBNK_COLUMNS])
            qs = TBNKPanel.objects.select_related(
                "recipient_visit__recipient", "donor"
            ).order_by("pk")
            for p in qs:
                if p.recipient_visit_id is not None:
                    parent_type, parent_id = "recipient_visit", p.recipient_visit_id
                    offset = _offset(p.drawn_date, p.recipient_visit.recipient.kt_date)
                else:
                    parent_type, parent_id, offset = "donor", p.donor_id, ""
                subset_cells = [
                    getattr(p, f) if getattr(p, f) is not None else ""
                    for f in TBNK_SUBSET_FIELDS
                ]
                ratio = p.cd4_cd8_ratio
                ratio_cell = ratio if ratio is not None else ""
                w.writerow([p.id, parent_type, parent_id, *subset_cells, ratio_cell, offset])

    def _write_renal(self, base):
        with (base / "renalfunction.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in RENAL_COLUMNS])
            qs = RenalFunction.objects.select_related(
                "recipient_visit__recipient", "donor"
            ).order_by("pk")
            for rf in qs:
                if rf.recipient_visit_id is not None:
                    parent_type, parent_id = "recipient_visit", rf.recipient_visit_id
                    offset = _offset(rf.drawn_date, rf.recipient_visit.recipient.kt_date)
                else:
                    parent_type, parent_id, offset = "donor", rf.donor_id, ""
                cr_cell = rf.serum_creatinine_mg_dl if rf.serum_creatinine_mg_dl is not None else ""
                egfr = rf.eGFR
                egfr_cell = egfr if egfr is not None else ""
                w.writerow([rf.id, parent_type, parent_id, cr_cell, egfr_cell,
                            rf.result_status, offset])

    def _write_druglevels(self, base):
        with (base / "druglevel.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in DRUGLEVEL_COLUMNS])
            qs = DrugLevel.objects.select_related(
                "recipient_visit__recipient", "donor"
            ).order_by("pk")
            for d in qs:
                if d.recipient_visit_id is not None:
                    parent_type, parent_id = "recipient_visit", d.recipient_visit_id
                    offset = _offset(d.drawn_date, d.recipient_visit.recipient.kt_date)
                else:
                    parent_type, parent_id, offset = "donor", d.donor_id, ""
                value_cell = d.value if d.value is not None else ""
                w.writerow([d.id, parent_type, parent_id, d.analyte, value_cell,
                            d.result_status, offset])

    def _write_episodes(self, base):
        with (base / "cmvepisode.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in EPISODE_COLUMNS])
            for r in Recipient.objects.order_by("pk"):
                # Episodes are derived (Topic #4 rules) entirely in day-offset
                # space, so no calendar date can reach this file.
                for e in r.cmv_episodes:
                    end_cell = e.end_day if e.end_day is not None else ""
                    w.writerow([r.subject_id, e.episode_index, e.start_day,
                                end_cell, e.severity_tier])

    def _write_medicationcourses(self, base):
        with (base / "medicationcourse.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in MEDICATIONCOURSE_COLUMNS])
            qs = MedicationCourse.objects.select_related("recipient").order_by("pk")
            for c in qs:
                kt = c.recipient.kt_date
                end_off = _offset(c.end_date, kt) if c.end_date is not None else ""
                dur = c.duration_days if c.duration_days is not None else ""
                w.writerow([
                    c.id, c.recipient.subject_id, c.drug_class, c.agent,
                    str(c.dose_amount), c.dose_unit, c.frequency, c.course_type,
                    _offset(c.start_date, kt), end_off, dur,
                    _bool3(c.completed_per_protocol), c.early_discontinuation_reason,
                    c.dose_reduction_count if c.dose_reduction_count is not None else "",
                    c.change_direction,
                    _bool3(c.cmv_management_intent),
                ])

    def _write_rejectionepisodes(self, base):
        with (base / "rejectionepisode.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in REJECTIONEPISODE_COLUMNS])
            qs = RejectionEpisode.objects.select_related("recipient").order_by("pk")
            for e in qs:
                kt = e.recipient.kt_date
                biopsy_off = _offset(e.biopsy_date, kt) if e.biopsy_date is not None else ""
                resolved_off = _offset(e.resolved_date, kt) if e.resolved_date is not None else ""
                w.writerow([
                    e.id, e.recipient.subject_id, _offset(e.onset_date, kt),
                    e.rejection_type, e.banff_grade, _bool3(e.biopsy_proven),
                    biopsy_off, resolved_off,
                ])

    def _write_hospitalizations(self, base):
        with (base / "hospitalization.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in HOSPITALIZATION_COLUMNS])
            qs = Hospitalization.objects.select_related("recipient").order_by("pk")
            for h in qs:
                kt = h.recipient.kt_date
                discharge_off = _offset(h.discharge_date, kt) if h.discharge_date is not None else ""
                los = h.length_of_stay_days if h.length_of_stay_days is not None else ""
                w.writerow([
                    h.id, h.recipient.subject_id, _offset(h.admit_date, kt),
                    discharge_off, los, h.disposition,
                    h.cmv_attribution_id if h.cmv_attribution_id is not None else "",
                    h.rejection_attribution_id if h.rejection_attribution_id is not None else "",
                    _bool3(h.cmv_attributable),
                ])

    def _write_aliquots(self, base):
        with (base / "aliquot.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in ALIQUOT_COLUMNS])
            qs = Aliquot.objects.select_related(
                "recipient_visit__recipient"
            ).order_by("pk")
            for a in qs:
                # No visit anchor -> no kt_date -> collected date stays blank, never
                # a calendar date (the donor/DonorVisit precedent). destruction
                # certificate (free text) is deliberately not exported.
                if a.recipient_visit_id is not None:
                    recipient = a.recipient_visit.recipient
                    recipient_cell = recipient.subject_id
                    offset = _offset(a.collected_date, recipient.kt_date)
                else:
                    recipient_cell, offset = "", ""
                w.writerow([
                    a.id, recipient_cell, a.matrix, offset,
                    str(a.initial_volume_ul), str(a.remaining_ul), a.thaw_count,
                ])

    def _write_genotyping_results(self, base):
        with (base / "genotypingresult.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in GENOTYPINGRESULT_COLUMNS])
            qs = GenotypingResult.objects.select_related(
                "aliquot__recipient_visit__recipient"
            ).order_by("pk")
            for g in qs:
                # subject + sample date are derived THROUGH the tube; the date only
                # ever leaves as an offset (blank when the straw has no kt anchor).
                recipient = g.subject
                if recipient is not None:
                    subject_cell = recipient.subject_id
                    offset = _offset(g.sample_date, recipient.kt_date)
                else:
                    subject_cell, offset = "", ""
                w.writerow([g.id, subject_cell, g.assay_type, offset, g.qpcr_rollup])

    def _write_genotype_calls(self, base):
        with (base / "genotypecall.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in GENOTYPECALL_COLUMNS])
            for c in GenotypeCall.objects.order_by("pk"):
                # entered_by/reviewed_by (staff names) and is_locked are never
                # exported — only the de-identified call codes leave.
                w.writerow([c.id, c.result_id, c.locus, c.allele, c.sanger_call or ""])

    def _write_concordance_pairs(self, base):
        with (base / "concordancepair.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in CONCORDANCEPAIR_COLUMNS])
            qs = ConcordancePair.objects.select_related("recipient").order_by("pk")
            for p in qs:
                # suggested_concordance_call / co_resolved_count are derived at read
                # from the stored calls (the pure grader) so the export reproduces.
                # reviewed_by/reviewed_at (staff attribution) are never exported.
                w.writerow([
                    p.id, p.recipient.subject_id, p.concordance_call,
                    p.suggested_concordance_call, p.co_resolved_count,
                    p.superinfection_status,
                ])

    def _write_concordance_loci(self, base):
        with (base / "concordancelocus.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in CONCORDANCELOCUS_COLUMNS])
            qs = ConcordancePair.objects.select_related("recipient").order_by("pk")
            for p in qs:
                subject_id = p.recipient.subject_id
                # hypervariable-first → conserved → resistance-last, then by name.
                comparisons = sorted(
                    p.locus_comparisons(),
                    key=lambda c: (locus_order(c["locus"]), c["locus"]),
                )
                resistance_block_started = False
                for c in comparisons:
                    locus = c["locus"]
                    # A blank separator row precedes the resistance block (AC5).
                    if is_resistance(locus) and not resistance_block_started:
                        w.writerow([])
                        resistance_block_started = True
                    w.writerow([
                        p.id, subject_id, locus,
                        ";".join(sorted(c["allele_a_set"])),
                        ";".join(sorted(c["allele_b_set"])),
                        _bool3(c["resolved_a"]), _bool3(c["resolved_b"]),
                        _bool3(counted_for_strain_identity(locus)),
                        STRAIN_IDENTITY_NOTE if is_resistance(locus) else "",
                    ])

    def _write_manifest(self, base, version):
        specs = {
            "recipient.csv": RECIPIENT_COLUMNS,
            "donor.csv": DONOR_COLUMNS,
            "recipientvisit.csv": VISIT_COLUMNS,
            "donorvisit.csv": DONORVISIT_COLUMNS,
            "cmvserology.csv": SEROLOGY_COLUMNS,
            "cmvquantitative.csv": QUANTITATIVE_COLUMNS,
            "tbnkpanel.csv": TBNK_COLUMNS,
            "renalfunction.csv": RENAL_COLUMNS,
            "druglevel.csv": DRUGLEVEL_COLUMNS,
            "othercondition.csv": OTHERCONDITION_COLUMNS,
            "cmvepisode.csv": EPISODE_COLUMNS,
            "medicationcourse.csv": MEDICATIONCOURSE_COLUMNS,
            "rejectionepisode.csv": REJECTIONEPISODE_COLUMNS,
            "hospitalization.csv": HOSPITALIZATION_COLUMNS,
            "aliquot.csv": ALIQUOT_COLUMNS,
            "genotypingresult.csv": GENOTYPINGRESULT_COLUMNS,
            "genotypecall.csv": GENOTYPECALL_COLUMNS,
            "concordancepair.csv": CONCORDANCEPAIR_COLUMNS,
            "concordancelocus.csv": CONCORDANCELOCUS_COLUMNS,
        }
        files = {}
        for name, columns in specs.items():
            path = base / name
            data = path.read_bytes()
            row_count = max(data.decode().count("\n") - 1, 0) if data else 0
            files[name] = {
                "row_count": row_count,
                "sha256": hashlib.sha256(data).hexdigest(),
                "columns": dict(columns),
            }
        manifest = {"version": version, "files": files}
        (base / "manifest.json").write_text(json.dumps(manifest, indent=2))

    def _assert_no_identifier_leak(self, staging):
        for path in sorted(staging.glob("*.csv")):
            text = path.read_text()
            for rx in (DATE_RX, NAME_RX, MRN_RX, ADDRESS_RX):
                if rx.search(text):
                    raise CommandError(f"De-id check failed: a potential identifier leaked into {path.name}.")
