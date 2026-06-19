"""Slice 05 — CMVQuantitative: the long CMV viral-load series.

Stored LONG (one row per measurement, COBAS 5000, IU/mL, LoD = LoQ = 34.5) so a
patient's repeating draws form an ordered series the episode deriver (slice 07)
reads — never forced into a fixed-width shape. Mirrors CMVSerology's dual-FK
"exactly one parent" rule (recipient-visit XOR donor).
"""
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from renova.registry.models import CMVQuantitative, Donor, Recipient, RecipientVisit


@pytest.fixture
def recipient(db):
    return Recipient.objects.create(
        subject_id="SCMVR01", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )


@pytest.fixture
def visit(recipient):
    return RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_7", actual_visit_date=date(2025, 1, 15)
    )


@pytest.fixture
def donor(db):
    return Donor.objects.create(subject_id="DCMVD01", date_of_birth=date(1975, 1, 1), sex="F")


def test_assay_and_limits_documented_on_model():
    assert CMVQuantitative.ASSAY == "COBAS 5000"
    assert CMVQuantitative.LOD == Decimal("34.5")
    assert CMVQuantitative.LOQ == Decimal("34.5")


def test_long_shape_one_row_per_result_ordered_as_series(visit):
    """Three draws under one visit are three rows, returned chronologically."""
    CMVQuantitative.objects.create(
        recipient_visit=visit, value=Decimal("1500"), drawn_date=date(2025, 1, 20)
    )
    CMVQuantitative.objects.create(
        recipient_visit=visit, value=Decimal("500"), drawn_date=date(2025, 1, 10)
    )
    CMVQuantitative.objects.create(
        recipient_visit=visit, value=Decimal("9000"), drawn_date=date(2025, 1, 15)
    )
    series = list(CMVQuantitative.objects.all())
    assert len(series) == 3
    drawn = [q.drawn_date for q in series]
    assert drawn == sorted(drawn)  # ascending — an ordered series


def test_below_loq_is_still_a_row_no_clamping(visit):
    """A result below LoQ is recorded as-is (long shape); no clamp this slice."""
    q = CMVQuantitative(
        recipient_visit=visit, value=Decimal("10"), drawn_date=date(2025, 1, 10)
    )
    q.full_clean()
    q.save()
    assert CMVQuantitative.objects.get(pk=q.pk).value == Decimal("10")


def test_exactly_one_parent_visit_ok(visit):
    q = CMVQuantitative(
        recipient_visit=visit, value=Decimal("500"), drawn_date=date(2025, 1, 15)
    )
    q.full_clean()  # must not raise
    q.save()
    assert CMVQuantitative.objects.count() == 1


def test_donor_parent_ok(donor):
    q = CMVQuantitative(donor=donor, value=Decimal("500"), drawn_date=date(2024, 12, 1))
    q.full_clean()
    q.save()
    assert CMVQuantitative.objects.count() == 1


def test_neither_parent_rejected_by_clean(db):
    q = CMVQuantitative(value=Decimal("500"), drawn_date=date(2025, 1, 15))
    with pytest.raises(ValidationError):
        q.clean()


def test_both_parents_rejected_by_clean(visit, donor):
    q = CMVQuantitative(
        recipient_visit=visit, donor=donor, value=Decimal("500"), drawn_date=date(2025, 1, 15)
    )
    with pytest.raises(ValidationError):
        q.clean()


def test_both_parents_rejected_by_db_constraint(visit, donor):
    """Bypassing clean() still fails: the DB CheckConstraint is the hard floor."""
    q = CMVQuantitative(
        recipient_visit=visit, donor=donor, value=Decimal("500"), drawn_date=date(2025, 1, 15)
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            q.save()


def test_neither_parent_rejected_by_db_constraint(db):
    q = CMVQuantitative(value=Decimal("500"), drawn_date=date(2025, 1, 15))
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            q.save()


def test_reported_requires_value(visit):
    q = CMVQuantitative(
        recipient_visit=visit, result_status="reported", value=None, drawn_date=date(2025, 1, 15)
    )
    with pytest.raises(ValidationError):
        q.clean()


def test_missing_must_not_carry_value(visit):
    q = CMVQuantitative(
        recipient_visit=visit, result_status="missing", value=Decimal("500"),
        drawn_date=date(2025, 1, 15),
    )
    with pytest.raises(ValidationError):
        q.clean()


def test_missing_observation_value_status_db_constraint(visit):
    q = CMVQuantitative(
        recipient_visit=visit, result_status="missing", value=Decimal("500"),
        drawn_date=date(2025, 1, 15),
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            q.save()


def test_history_tracked(visit):
    q = CMVQuantitative.objects.create(
        recipient_visit=visit, value=Decimal("500"), drawn_date=date(2025, 1, 15)
    )
    assert q.history.count() == 1
