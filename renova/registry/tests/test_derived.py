from datetime import date
from decimal import Decimal

import pytest

from renova.registry.models import CMVSerology, Recipient, RecipientVisit


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


# --- Slice 05: pre-KT IgG serostatus computed ONCE from the pre_kt assay ---


def _recipient(db, **kw):
    return Recipient.objects.create(
        subject_id="SCMVR05", date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=date(2025, 1, 1), **kw
    )


def _pre_kt_igg(recipient, value):
    v = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="pre_kt", actual_visit_date=date(2025, 1, 1)
    )
    CMVSerology.objects.create(
        recipient_visit=v, value=value, drawn_date=date(2025, 1, 1)
    )


@pytest.mark.django_db
def test_pre_kt_igg_serostatus_is_derived_not_stored():
    field_names = {f.name for f in Recipient._meta.get_fields()}
    assert "pre_kt_igg_serostatus" not in field_names
    assert isinstance(Recipient.pre_kt_igg_serostatus, property)


@pytest.mark.django_db
def test_pre_kt_igg_serostatus_positive():
    r = _recipient(None)
    _pre_kt_igg(r, Decimal("3.0"))  # >= 2.0 -> POS
    assert r.pre_kt_igg_serostatus == "POS"


@pytest.mark.django_db
def test_pre_kt_igg_serostatus_negative():
    r = _recipient(None)
    _pre_kt_igg(r, Decimal("1.0"))  # < 2.0 -> NEG
    assert r.pre_kt_igg_serostatus == "NEG"


@pytest.mark.django_db
def test_pre_kt_igg_serostatus_none_without_pre_kt_visit():
    r = _recipient(None)
    assert r.pre_kt_igg_serostatus is None


@pytest.mark.django_db
def test_pre_kt_igg_serostatus_none_when_igg_missing():
    r = _recipient(None)
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="pre_kt", actual_visit_date=date(2025, 1, 1)
    )
    CMVSerology.objects.create(
        recipient_visit=v, result_status="missing", drawn_date=date(2025, 1, 1)
    )
    assert r.pre_kt_igg_serostatus is None


@pytest.mark.django_db
def test_pre_kt_igg_serostatus_equals_the_igg_derivation_one_canonical_value():
    """AC3: the value stratification (Obj 4a) and attribution (Obj 5) would each
    read is the SAME single canonical derivation off the pre_kt IgG result."""
    r = _recipient(None)
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="pre_kt", actual_visit_date=date(2025, 1, 1)
    )
    s = CMVSerology.objects.create(
        recipient_visit=v, value=Decimal("5.0"), drawn_date=date(2025, 1, 1)
    )
    derived = "POS" if s.is_positive else "NEG"
    assert r.pre_kt_igg_serostatus == derived
