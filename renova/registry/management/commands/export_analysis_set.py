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
)

# A bare calendar date should never appear in any output file.
DATE_RX = re.compile(r"\d{4}-\d{2}-\d{2}")
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
]
DONOR_COLUMNS = [
    ("subject_id", "c"),
    ("sex", "c"),
    ("donor_type", "c"),
    ("relation", "c"),
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
            self._write_manifest(staging, version)
            self._assert_no_identifier_leak(staging)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        staging.rename(base)
        self.stdout.write(self.style.SUCCESS(f"Wrote de-identified snapshot to {base}"))

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
                     r.pre_kt_igg_serostatus or "",
                     _bool3(s.any_episode_le_6mo) if s else "",
                     s.time_to_first_episode if s else "",
                     _bool3(s.time_to_first_censored) if s else "",
                     s.episode_count if s else "",
                     s.person_time if s else ""]
                )

    def _write_donors(self, base):
        with (base / "donor.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in DONOR_COLUMNS])
            for d in Donor.objects.order_by("pk"):
                w.writerow(
                    [d.subject_id, d.sex, d.donor_type or "", d.relation or "",
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
