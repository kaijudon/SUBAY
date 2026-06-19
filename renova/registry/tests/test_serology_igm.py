"""Slice 05 — CMVSerology IgM channel (the WIDE second channel).

The existing unprefixed `value`/`result_status`/`is_positive` ARE the IgG channel
(CMV serostatus = IgG, Snibe Maglumi 600, 2.0 AU/mL — DEC-016). This slice ADDS a
parallel IgM channel: `igm_value`, `igm_status`, derived `igm_positive` at the SAME
locked 2.0 AU/mL single cutoff — ≥2.0 positive, <2.0 negative, NO equivocal band,
positive flag NEVER stored.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from renova.registry.models import CMVSerology, Recipient, RecipientVisit


@pytest.fixture
def visit(db):
    r = Recipient.objects.create(
        subject_id="SCMVR01", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    return RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 15)
    )


def test_igm_positive_is_derived_not_stored():
    field_names = {f.name for f in CMVSerology._meta.get_fields()}
    assert "igm_positive" not in field_names  # derived property, never a column
    assert isinstance(CMVSerology.igm_positive, property)


@pytest.mark.parametrize(
    "igm,expected",
    [
        (Decimal("2.0"), True),  # exactly at cutoff -> positive
        (Decimal("2.01"), True),
        (Decimal("1.99"), False),
        (Decimal("0"), False),
        (None, None),  # not measured -> undefined, never a third "equivocal" state
    ],
)
def test_igm_positive_single_cutoff_no_equivocal(igm, expected):
    s = CMVSerology(igm_value=igm)
    assert s.igm_positive is expected


def test_igm_channel_is_independent_of_igg(visit):
    """IgG positive, IgM negative on the same draw — two distinct channels."""
    s = CMVSerology(
        recipient_visit=visit,
        value=Decimal("3.0"),  # IgG positive
        igm_value=Decimal("1.0"),  # IgM negative
        igm_status="reported",
        drawn_date=date(2025, 1, 15),
    )
    s.full_clean()
    s.save()
    assert s.is_positive is True
    assert s.igm_positive is False


def test_igm_defaults_to_missing_when_absent(visit):
    """A serology entered with only an IgG value has no IgM observation."""
    s = CMVSerology(recipient_visit=visit, value=Decimal("3.0"), drawn_date=date(2025, 1, 15))
    s.full_clean()  # must not raise — IgM defaults missing/null, mirror constraint holds
    s.save()
    assert s.igm_status == "missing"
    assert s.igm_value is None
    assert s.igm_positive is None


def test_igm_reported_requires_value(visit):
    s = CMVSerology(
        recipient_visit=visit, value=Decimal("3.0"), igm_status="reported", igm_value=None,
        drawn_date=date(2025, 1, 15),
    )
    with pytest.raises(ValidationError):
        s.clean()


def test_igm_missing_must_not_carry_value(visit):
    s = CMVSerology(
        recipient_visit=visit, value=Decimal("3.0"), igm_status="missing",
        igm_value=Decimal("1.0"), drawn_date=date(2025, 1, 15),
    )
    with pytest.raises(ValidationError):
        s.clean()


def test_igm_value_status_db_constraint(visit):
    """Bypassing clean(): the DB CheckConstraint mirrors the IgG one."""
    s = CMVSerology(
        recipient_visit=visit, value=Decimal("3.0"), igm_status="missing",
        igm_value=Decimal("1.0"), drawn_date=date(2025, 1, 15),
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            s.save()
