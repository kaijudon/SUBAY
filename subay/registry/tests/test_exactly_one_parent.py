from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from subay.registry.models import CMVSerology, Donor, Recipient, RecipientVisit


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


def test_exactly_one_parent_visit_ok(visit):
    s = CMVSerology(recipient_visit=visit, value=Decimal("3.0"), drawn_date=date(2025, 1, 15))
    s.full_clean()  # must not raise
    s.save()
    assert CMVSerology.objects.count() == 1


def test_neither_parent_rejected_by_clean(db):
    s = CMVSerology(value=Decimal("3.0"), drawn_date=date(2025, 1, 15))
    with pytest.raises(ValidationError):
        s.clean()


def test_both_parents_rejected_by_clean(visit, donor):
    s = CMVSerology(recipient_visit=visit, donor=donor, value=Decimal("3.0"), drawn_date=date(2025, 1, 15))
    with pytest.raises(ValidationError):
        s.clean()


def test_both_parents_rejected_by_db_constraint(visit, donor):
    """Bypassing clean() still fails: the DB CheckConstraint is the hard floor."""
    s = CMVSerology(recipient_visit=visit, donor=donor, value=Decimal("3.0"), drawn_date=date(2025, 1, 15))
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            s.save()
