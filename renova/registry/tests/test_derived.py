from datetime import date

import pytest

from renova.registry.models import Recipient


@pytest.mark.django_db
def test_age_derived_at_kt_date():
    r = Recipient.objects.create(
        subject_id="SCMVR02", date_of_birth=date(1980, 6, 15), sex="M", kt_date=date(2025, 1, 1)
    )
    assert r.age == 44  # birthday not yet reached by 1 Jan 2025


@pytest.mark.parametrize(
    "donor,recip,expected",
    [
        ("POS", "NEG", "high"),  # D+/R-
        ("POS", "POS", "intermediate"),  # R+
        ("NEG", "POS", "intermediate"),  # R+
        ("NEG", "NEG", "low"),  # D-/R-
        (None, "NEG", None),  # incomplete -> undefined
    ],
)
def test_risk_stratum_from_serostatus(donor, recip, expected):
    r = Recipient(
        subject_id="SCMVR03",
        date_of_birth=date(1980, 1, 1),
        sex="M",
        kt_date=date(2025, 1, 1),
        donor_serostatus=donor,
        recipient_serostatus=recip,
    )
    assert r.risk_stratum == expected
