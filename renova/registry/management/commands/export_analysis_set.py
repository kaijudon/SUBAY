"""export_analysis_set — minimal de-identified snapshot (Slice 0).

Writes one CSV per model to analysis_sets/<version>/. Every date becomes an
integer day-offset from the recipient's kt_date (transplant = day 0). No
calendar date and no date-of-birth ever leaves. Refuses to overwrite a frozen
version. Slice 01 hardens this into the full audited chokepoint (manifest.json
+ per-file SHA-256 + a full identifier-leak refuse).
"""
import csv
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from renova.registry.models import CMVSerology, Donor, Recipient, RecipientVisit

# A bare calendar date should never appear in any output file.
DATE_RX = re.compile(r"\d{4}-\d{2}-\d{2}")


def _offset(d, kt_date):
    """Integer days from transplant (day 0). Negative for pre-KT dates."""
    return (d - kt_date).days


class Command(BaseCommand):
    help = "Write a versioned, de-identified CSV snapshot (dates as day-offsets from kt_date)."

    def add_arguments(self, parser):
        parser.add_argument("version", help="Snapshot version, e.g. v0.1")
        parser.add_argument("--outdir", default="analysis_sets")

    def handle(self, *args, version, outdir, **options):
        base = Path(outdir) / version
        if base.exists():
            raise CommandError(f"{base} already exists; refusing to overwrite a frozen snapshot.")
        base.mkdir(parents=True)

        self._write_recipients(base)
        self._write_donors(base)
        self._write_visits(base)
        self._write_serologies(base)
        self._assert_no_calendar_dates(base)

        self.stdout.write(self.style.SUCCESS(f"Wrote de-identified snapshot to {base}"))

    def _write_recipients(self, base):
        with (base / "recipient.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(
                ["subject_id", "sex", "age", "risk_stratum", "donor_serostatus", "recipient_serostatus"]
            )
            for r in Recipient.objects.all():
                w.writerow(
                    [r.subject_id, r.sex, r.age, r.risk_stratum,
                     r.donor_serostatus or "", r.recipient_serostatus or ""]
                )

    def _write_donors(self, base):
        with (base / "donor.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["subject_id", "sex"])
            for d in Donor.objects.all():
                w.writerow([d.subject_id, d.sex])

    def _write_visits(self, base):
        with (base / "recipientvisit.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "recipient", "day_offset"])
            for v in RecipientVisit.objects.select_related("recipient"):
                w.writerow([v.id, v.recipient_id, _offset(v.visit_date, v.recipient.kt_date)])

    def _write_serologies(self, base):
        with (base / "cmvserology.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "parent_type", "parent_id", "value", "is_positive", "day_offset"])
            qs = CMVSerology.objects.select_related("recipient_visit__recipient", "donor")
            for s in qs:
                if s.recipient_visit_id is not None:
                    parent_type, parent_id = "recipient_visit", s.recipient_visit_id
                    offset = _offset(s.drawn_date, s.recipient_visit.recipient.kt_date)
                else:
                    # No recipient anchor for donor-attached labs in Slice 0.
                    parent_type, parent_id, offset = "donor", s.donor_id, ""
                w.writerow([s.id, parent_type, parent_id, s.value, s.is_positive, offset])

    def _assert_no_calendar_dates(self, base):
        for path in base.glob("*.csv"):
            if DATE_RX.search(path.read_text()):
                raise CommandError(f"De-id check failed: a calendar date leaked into {path.name}.")
