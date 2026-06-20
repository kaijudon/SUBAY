"""Slice 06 — RenalFunction: raw creatinine in, eGFR derived out.

Stores raw serum creatinine only. eGFR is DERIVED via CKD-EPI 2021 (race-free),
never stored, and any lab-reported eGFR is IGNORED — there is no column to hold
it, so no site-equation step-artifact can appear at a multi-site join (US 28).
Mirrors the dual-FK "exactly one parent" rule and the reported/missing pattern.
"""
import math
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from renova.registry.models import Donor, Recipient, RecipientVisit, RenalFunction


def ckd_epi_2021(scr, age, sex):
    """Independent re-derivation of CKD-EPI 2021 race-free, for test oracle."""
    kappa = 0.7 if sex == "F" else 0.9
    alpha = -0.241 if sex == "F" else -0.302
    ratio = float(scr) / kappa
    egfr = (
        142
        * (min(ratio, 1.0) ** alpha)
        * (max(ratio, 1.0) ** -1.200)
        * (0.9938 ** age)
        * (1.012 if sex == "F" else 1.0)
    )
    return egfr


@pytest.fixture
def recipient(db):
    # DOB 1980-01-01, drawn 2025-06-01 -> age 45 at draw.
    return Recipient.objects.create(
        subject_id="SCMVR01", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )


@pytest.fixture
def visit(recipient):
    return RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_180", actual_visit_date=date(2025, 6, 1)
    )


@pytest.fixture
def donor(db):
    # DOB 1975-01-01, drawn 2025-06-01 -> age 50 at draw.
    return Donor.objects.create(subject_id="DCMVD01", date_of_birth=date(1975, 1, 1), sex="F")


def test_egfr_is_derived_not_stored():
    field_names = {f.name for f in RenalFunction._meta.get_fields()}
    assert "eGFR" not in field_names
    assert "egfr" not in field_names
    assert isinstance(RenalFunction.eGFR, property)


def test_no_lab_reported_egfr_field():
    """Any lab eGFR is ignored by never storing it — no column may exist."""
    field_names = {f.name for f in RenalFunction._meta.get_fields()}
    for n in field_names:
        assert "egfr" not in n.lower(), f"a lab-reported eGFR column leaked in: {n}"


def test_raw_creatinine_round_trips_unchanged(visit):
    rf = RenalFunction.objects.create(
        recipient_visit=visit, serum_creatinine_mg_dl=Decimal("1.23"), drawn_date=date(2025, 6, 1)
    )
    assert RenalFunction.objects.get(pk=rf.pk).serum_creatinine_mg_dl == Decimal("1.23")


def test_egfr_matches_ckd_epi_2021_male(visit):
    rf = RenalFunction.objects.create(
        recipient_visit=visit, serum_creatinine_mg_dl=Decimal("1.0"), drawn_date=date(2025, 6, 1)
    )
    expected = ckd_epi_2021(Decimal("1.0"), 45, "M")
    assert rf.eGFR == pytest.approx(expected, abs=0.01)
    assert rf.eGFR == pytest.approx(94.59, abs=0.1)  # pinned published-style value


def test_egfr_matches_ckd_epi_2021_female(donor):
    rf = RenalFunction.objects.create(
        donor=donor, serum_creatinine_mg_dl=Decimal("0.8"), drawn_date=date(2025, 6, 1)
    )
    expected = ckd_epi_2021(Decimal("0.8"), 50, "F")
    assert rf.eGFR == pytest.approx(expected, abs=0.01)
    assert rf.eGFR == pytest.approx(89.70, abs=0.1)


def test_egfr_none_when_creatinine_missing(visit):
    rf = RenalFunction.objects.create(
        recipient_visit=visit, result_status="missing", drawn_date=date(2025, 6, 1)
    )
    assert rf.eGFR is None


def test_exactly_one_parent_visit_ok(visit):
    rf = RenalFunction(
        recipient_visit=visit, serum_creatinine_mg_dl=Decimal("1.0"), drawn_date=date(2025, 6, 1)
    )
    rf.full_clean()
    rf.save()
    assert RenalFunction.objects.count() == 1


def test_donor_parent_ok(donor):
    rf = RenalFunction(donor=donor, serum_creatinine_mg_dl=Decimal("1.0"), drawn_date=date(2024, 12, 1))
    rf.full_clean()
    rf.save()
    assert RenalFunction.objects.count() == 1


def test_neither_parent_rejected_by_clean(db):
    rf = RenalFunction(serum_creatinine_mg_dl=Decimal("1.0"), drawn_date=date(2025, 6, 1))
    with pytest.raises(ValidationError):
        rf.clean()


def test_both_parents_rejected_by_clean(visit, donor):
    rf = RenalFunction(
        recipient_visit=visit, donor=donor, serum_creatinine_mg_dl=Decimal("1.0"),
        drawn_date=date(2025, 6, 1),
    )
    with pytest.raises(ValidationError):
        rf.clean()


def test_both_parents_rejected_by_db_constraint(visit, donor):
    rf = RenalFunction(
        recipient_visit=visit, donor=donor, serum_creatinine_mg_dl=Decimal("1.0"),
        drawn_date=date(2025, 6, 1),
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            rf.save()


def test_neither_parent_rejected_by_db_constraint(db):
    rf = RenalFunction(serum_creatinine_mg_dl=Decimal("1.0"), drawn_date=date(2025, 6, 1))
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            rf.save()


def test_reported_requires_value(visit):
    rf = RenalFunction(
        recipient_visit=visit, result_status="reported", serum_creatinine_mg_dl=None,
        drawn_date=date(2025, 6, 1),
    )
    with pytest.raises(ValidationError):
        rf.clean()


def test_missing_must_not_carry_value(visit):
    rf = RenalFunction(
        recipient_visit=visit, result_status="missing", serum_creatinine_mg_dl=Decimal("1.0"),
        drawn_date=date(2025, 6, 1),
    )
    with pytest.raises(ValidationError):
        rf.clean()


def test_missing_observation_value_status_db_constraint(visit):
    rf = RenalFunction(
        recipient_visit=visit, result_status="missing", serum_creatinine_mg_dl=Decimal("1.0"),
        drawn_date=date(2025, 6, 1),
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            rf.save()


def test_history_tracked(visit):
    rf = RenalFunction.objects.create(
        recipient_visit=visit, serum_creatinine_mg_dl=Decimal("1.0"), drawn_date=date(2025, 6, 1)
    )
    assert rf.history.count() == 1
