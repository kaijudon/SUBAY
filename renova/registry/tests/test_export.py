from datetime import date
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from renova.registry.models import CMVSerology, Recipient, RecipientVisit


@pytest.fixture
def seeded(db):
    r = Recipient.objects.create(
        subject_id="SCMVR07",
        date_of_birth=date(1980, 1, 1),
        sex="M",
        kt_date=date(2025, 1, 1),
        donor_serostatus="POS",
        recipient_serostatus="NEG",
    )
    v = RecipientVisit.objects.create(recipient=r, visit_date=date(2025, 1, 15))
    CMVSerology.objects.create(recipient_visit=v, value=Decimal("3.0"), drawn_date=date(2025, 1, 15))
    return r


def test_export_writes_day_offsets_and_no_calendar_date(seeded, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    assert "14" in (out / "recipientvisit.csv").read_text()  # 15 Jan is 14 days after kt day 0
    assert "SCMVR07" in (out / "recipient.csv").read_text()  # pseudonym present

    for f in out.glob("*.csv"):
        text = f.read_text()
        assert "2025-01-15" not in text  # no calendar date
        assert "1980-01-01" not in text  # no date of birth


def test_export_refuses_to_overwrite_frozen_version(seeded, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    with pytest.raises(CommandError):
        call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
