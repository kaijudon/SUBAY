"""Slice 06 — TBNKPanel: the wide lymphocyte-subset panel.

Stored WIDE — co-drawn subsets stay one row (the wide-vs-long-by-variability
rule: a panel's seven subsets are always drawn together). Each subset is two
stored columns (absolute count cells/µL + % lymphocytes); cd4_cd8_ratio is
DERIVED (derive-don't-store), never a column. Mirrors CMVQuantitative's dual-FK
"exactly one parent" rule (recipient-visit XOR donor).
"""
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from subay.registry.models import Donor, Recipient, RecipientVisit, TBNKPanel


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


SUBSET_FIELDS = [
    "cd3_count", "cd3_pct",
    "cd3_cd4_count", "cd3_cd4_pct",
    "cd3_cd8_count", "cd3_cd8_pct",
    "cd19_count", "cd19_pct",
    "nk_count", "nk_pct",
    "cd4_cd8_dp_count", "cd4_cd8_dp_pct",
    "cd4_cd8_dn_count", "cd4_cd8_dn_pct",
]


def test_seven_subsets_present_as_count_and_pct_stored_fields():
    """Wide shape: 7 subsets × {count, %lymph} = 14 stored measure columns."""
    field_names = {f.name for f in TBNKPanel._meta.get_fields()}
    for name in SUBSET_FIELDS:
        assert name in field_names, f"missing stored subset column {name}"


def test_cd4_cd8_ratio_is_derived_not_stored():
    field_names = {f.name for f in TBNKPanel._meta.get_fields()}
    assert "cd4_cd8_ratio" not in field_names  # derived, never a column
    assert isinstance(TBNKPanel.cd4_cd8_ratio, property)


def test_cd4_cd8_ratio_math(visit):
    p = TBNKPanel.objects.create(
        recipient_visit=visit, drawn_date=date(2025, 1, 15),
        cd3_cd4_count=Decimal("800"), cd3_cd8_count=Decimal("400"),
    )
    assert p.cd4_cd8_ratio == Decimal("2")


def test_cd4_cd8_ratio_none_when_numerator_missing(visit):
    p = TBNKPanel.objects.create(
        recipient_visit=visit, drawn_date=date(2025, 1, 15), cd3_cd8_count=Decimal("400")
    )
    assert p.cd4_cd8_ratio is None


def test_cd4_cd8_ratio_none_when_denominator_zero(visit):
    p = TBNKPanel.objects.create(
        recipient_visit=visit, drawn_date=date(2025, 1, 15),
        cd3_cd4_count=Decimal("800"), cd3_cd8_count=Decimal("0"),
    )
    assert p.cd4_cd8_ratio is None


def test_exactly_one_parent_visit_ok(visit):
    p = TBNKPanel(recipient_visit=visit, drawn_date=date(2025, 1, 15))
    p.full_clean()  # must not raise
    p.save()
    assert TBNKPanel.objects.count() == 1


def test_donor_parent_ok(donor):
    p = TBNKPanel(donor=donor, drawn_date=date(2024, 12, 1))
    p.full_clean()
    p.save()
    assert TBNKPanel.objects.count() == 1


def test_neither_parent_rejected_by_clean(db):
    p = TBNKPanel(drawn_date=date(2025, 1, 15))
    with pytest.raises(ValidationError):
        p.clean()


def test_both_parents_rejected_by_clean(visit, donor):
    p = TBNKPanel(recipient_visit=visit, donor=donor, drawn_date=date(2025, 1, 15))
    with pytest.raises(ValidationError):
        p.clean()


def test_both_parents_rejected_by_db_constraint(visit, donor):
    p = TBNKPanel(recipient_visit=visit, donor=donor, drawn_date=date(2025, 1, 15))
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            p.save()


def test_neither_parent_rejected_by_db_constraint(db):
    p = TBNKPanel(drawn_date=date(2025, 1, 15))
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            p.save()


def test_history_tracked(visit):
    p = TBNKPanel.objects.create(recipient_visit=visit, drawn_date=date(2025, 1, 15))
    assert p.history.count() == 1
