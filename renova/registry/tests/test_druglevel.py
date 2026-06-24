"""Slice 06 — DrugLevel: tacrolimus/everolimus troughs, stored LONG.

One row per trough result (the real drug-exposure variable on its own grain),
separate from any prescription/medication model (slice 08 is OUT) so exposure is
analyzable independently. Mirrors the dual-FK "exactly one parent" rule and the
reported/missing pattern.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from renova.registry.models import Donor, DrugLevel, Recipient, RecipientVisit


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


def test_long_shape_one_row_per_result_ordered_as_series(visit):
    DrugLevel.objects.create(
        recipient_visit=visit, analyte="tacrolimus", value=Decimal("8.0"),
        drawn_date=date(2025, 1, 20),
    )
    DrugLevel.objects.create(
        recipient_visit=visit, analyte="tacrolimus", value=Decimal("6.0"),
        drawn_date=date(2025, 1, 10),
    )
    DrugLevel.objects.create(
        recipient_visit=visit, analyte="everolimus", value=Decimal("3.0"),
        drawn_date=date(2025, 1, 15),
    )
    series = list(DrugLevel.objects.all())
    assert len(series) == 3
    drawn = [d.drawn_date for d in series]
    assert drawn == sorted(drawn)  # ascending — an ordered series


def test_analyte_choices():
    field = DrugLevel._meta.get_field("analyte")
    values = {c[0] for c in field.choices}
    assert values == {"tacrolimus", "everolimus"}


def test_no_prescription_fk():
    """DrugLevel is standalone (slice 08 is OUT) — no FK to any prescription."""
    for f in DrugLevel._meta.get_fields():
        if f.is_relation and f.many_to_one:
            assert f.name in {"recipient_visit", "donor", "entered_by", "verified_by"}, f"unexpected FK: {f.name}"


def test_exactly_one_parent_visit_ok(visit):
    d = DrugLevel(
        recipient_visit=visit, analyte="tacrolimus", value=Decimal("8.0"),
        drawn_date=date(2025, 1, 15),
    )
    d.full_clean()
    d.save()
    assert DrugLevel.objects.count() == 1


def test_donor_parent_ok(donor):
    d = DrugLevel(donor=donor, analyte="tacrolimus", value=Decimal("8.0"), drawn_date=date(2024, 12, 1))
    d.full_clean()
    d.save()
    assert DrugLevel.objects.count() == 1


def test_neither_parent_rejected_by_clean(db):
    d = DrugLevel(analyte="tacrolimus", value=Decimal("8.0"), drawn_date=date(2025, 1, 15))
    with pytest.raises(ValidationError):
        d.clean()


def test_both_parents_rejected_by_clean(visit, donor):
    d = DrugLevel(
        recipient_visit=visit, donor=donor, analyte="tacrolimus", value=Decimal("8.0"),
        drawn_date=date(2025, 1, 15),
    )
    with pytest.raises(ValidationError):
        d.clean()


def test_both_parents_rejected_by_db_constraint(visit, donor):
    d = DrugLevel(
        recipient_visit=visit, donor=donor, analyte="tacrolimus", value=Decimal("8.0"),
        drawn_date=date(2025, 1, 15),
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            d.save()


def test_neither_parent_rejected_by_db_constraint(db):
    d = DrugLevel(analyte="tacrolimus", value=Decimal("8.0"), drawn_date=date(2025, 1, 15))
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            d.save()


def test_reported_requires_value(visit):
    d = DrugLevel(
        recipient_visit=visit, analyte="tacrolimus", result_status="reported", value=None,
        drawn_date=date(2025, 1, 15),
    )
    with pytest.raises(ValidationError):
        d.clean()


def test_missing_must_not_carry_value(visit):
    d = DrugLevel(
        recipient_visit=visit, analyte="tacrolimus", result_status="missing", value=Decimal("8.0"),
        drawn_date=date(2025, 1, 15),
    )
    with pytest.raises(ValidationError):
        d.clean()


def test_missing_observation_value_status_db_constraint(visit):
    d = DrugLevel(
        recipient_visit=visit, analyte="tacrolimus", result_status="missing", value=Decimal("8.0"),
        drawn_date=date(2025, 1, 15),
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            d.save()


def test_history_tracked(visit):
    d = DrugLevel.objects.create(
        recipient_visit=visit, analyte="tacrolimus", value=Decimal("8.0"),
        drawn_date=date(2025, 1, 15),
    )
    assert d.history.count() == 1
