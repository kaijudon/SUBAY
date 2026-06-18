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

from renova.registry.models import CMVSerology, Donor, Recipient, RecipientVisit

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
]
DONOR_COLUMNS = [("subject_id", "c"), ("sex", "c")]
VISIT_COLUMNS = [("id", "i"), ("recipient", "c"), ("day_offset", "i")]
SEROLOGY_COLUMNS = [
    ("id", "i"),
    ("parent_type", "c"),
    ("parent_id", "c"),
    ("value", "d"),
    ("is_positive", "c"),
    ("day_offset", "i"),
]


def _offset(d, kt_date):
    """Integer days from transplant (day 0). Negative for pre-KT dates."""
    return (d - kt_date).days


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
            self._write_serologies(staging)
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
                w.writerow(
                    [r.subject_id, r.sex, r.age, r.risk_stratum,
                     r.donor_serostatus or "", r.recipient_serostatus or ""]
                )

    def _write_donors(self, base):
        with (base / "donor.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in DONOR_COLUMNS])
            for d in Donor.objects.order_by("pk"):
                w.writerow([d.subject_id, d.sex])

    def _write_visits(self, base):
        with (base / "recipientvisit.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([name for name, _ in VISIT_COLUMNS])
            for v in RecipientVisit.objects.select_related("recipient").order_by("pk"):
                w.writerow([v.id, v.recipient_id, _offset(v.visit_date, v.recipient.kt_date)])

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
                w.writerow([s.id, parent_type, parent_id, s.value, s.is_positive, offset])

    def _write_manifest(self, base, version):
        specs = {
            "recipient.csv": RECIPIENT_COLUMNS,
            "donor.csv": DONOR_COLUMNS,
            "recipientvisit.csv": VISIT_COLUMNS,
            "cmvserology.csv": SEROLOGY_COLUMNS,
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
