"""The walking-skeleton smoke test: exactly-one holds and the export is date-safe."""
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

from renova.registry.models import CMVSerology, Recipient, RecipientVisit


@pytest.mark.django_db
def test_smoke_exactly_one_and_export_is_date_safe(tmp_path):
    r = Recipient.objects.create(
        subject_id="SCMVR09", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    v = RecipientVisit.objects.create(recipient=r, visit_date=date(2025, 2, 1))

    # exactly-one parent: a parentless result is rejected.
    with pytest.raises(ValidationError):
        CMVSerology(value=Decimal("1.0"), drawn_date=date(2025, 2, 1)).clean()

    CMVSerology.objects.create(recipient_visit=v, value=Decimal("5.0"), drawn_date=date(2025, 2, 1))

    call_command("export_analysis_set", "v0.9", outdir=str(tmp_path))
    for f in (tmp_path / "v0.9").glob("*.csv"):
        assert "2025-" not in f.read_text()  # not a single calendar date escapes
