"""Slice 08 — MedicationCourse: structured numeric dose + prophylaxis/treatment split.

Dose is numeric (dose_amount + dose_unit + frequency), never free text, so a
mandated prophylaxis never masquerades as a clinical response. IS changes carry a
directional typology (reduction vs intensification) with an optional
CMV-management-intent tag so bidirectionality is visible. duration_days is
derived (derive-don't-store), never a column.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from renova.registry.models import MedicationCourse, Recipient


@pytest.fixture
def recipient(db):
    return Recipient.objects.create(
        subject_id="SCMVR01", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )


def _prophylaxis(recipient, **overrides):
    kwargs = dict(
        recipient=recipient,
        drug_class="antiviral",
        agent="valganciclovir",
        dose_amount=Decimal("900"),
        dose_unit="mg",
        frequency="qd",
        course_type="prophylaxis",
        start_date=date(2025, 1, 1),
    )
    kwargs.update(overrides)
    return MedicationCourse(**kwargs)


def _treatment(recipient, **overrides):
    kwargs = dict(
        recipient=recipient,
        drug_class="immunosuppressant",
        agent="tacrolimus",
        dose_amount=Decimal("2"),
        dose_unit="mg",
        frequency="bid",
        course_type="treatment",
        start_date=date(2025, 2, 1),
    )
    kwargs.update(overrides)
    return MedicationCourse(**kwargs)


# AC1 — structured numeric dose, no free-text; drug_class antiviral/immunosuppressant


def test_dose_amount_is_decimal_field():
    field = MedicationCourse._meta.get_field("dose_amount")
    assert field.get_internal_type() == "DecimalField"


def test_no_free_text_dose_field():
    """A free-text 'dose' column would defeat structured analysis — none may exist."""
    names = {f.name for f in MedicationCourse._meta.get_fields()}
    assert "dose" not in names
    assert {"dose_amount", "dose_unit", "frequency"} <= names


def test_drug_class_separates_antiviral_from_immunosuppressant():
    field = MedicationCourse._meta.get_field("drug_class")
    assert {c[0] for c in field.choices} == {"antiviral", "immunosuppressant"}


# AC2 — prophylaxis distinguishable from treatment escalation


def test_prophylaxis_course_clean_ok(recipient):
    c = _prophylaxis(recipient, completed_per_protocol=True)
    c.full_clean()
    c.save()
    assert MedicationCourse.objects.count() == 1


def test_treatment_course_clean_ok(recipient):
    c = _treatment(recipient, dose_reduction_count=2, dose_reduction_reason="leukopenia")
    c.full_clean()
    c.save()
    assert MedicationCourse.objects.count() == 1


def test_prophylaxis_fields_rejected_on_treatment_course(recipient):
    c = _treatment(recipient, completed_per_protocol=True)
    with pytest.raises(ValidationError):
        c.clean()


def test_early_discontinuation_reason_rejected_on_treatment_course(recipient):
    c = _treatment(recipient, early_discontinuation_reason="toxicity")
    with pytest.raises(ValidationError):
        c.clean()


def test_treatment_fields_rejected_on_prophylaxis_course(recipient):
    c = _prophylaxis(recipient, dose_reduction_count=1)
    with pytest.raises(ValidationError):
        c.clean()


def test_dose_reduction_reason_rejected_on_prophylaxis_course(recipient):
    c = _prophylaxis(recipient, dose_reduction_reason="leukopenia")
    with pytest.raises(ValidationError):
        c.clean()


def test_prophylaxis_fields_rejected_at_db_on_treatment(recipient):
    """DB CheckConstraint blocks a bare create that skips clean()."""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MedicationCourse.objects.create(
                recipient=recipient, drug_class="antiviral", agent="x",
                dose_amount=Decimal("1"), dose_unit="mg", frequency="qd",
                course_type="treatment", start_date=date(2025, 1, 1),
                completed_per_protocol=True,
            )


def test_treatment_fields_rejected_at_db_on_prophylaxis(recipient):
    """DB CheckConstraint blocks a bare create that skips clean()."""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MedicationCourse.objects.create(
                recipient=recipient, drug_class="antiviral", agent="x",
                dose_amount=Decimal("1"), dose_unit="mg", frequency="qd",
                course_type="prophylaxis", start_date=date(2025, 1, 1),
                dose_reduction_count=2,
            )


def test_duration_days_derived(recipient):
    c = _treatment(recipient, start_date=date(2025, 2, 1), end_date=date(2025, 2, 15))
    assert c.duration_days == 14


def test_duration_days_none_when_ongoing(recipient):
    c = _treatment(recipient, end_date=None)
    assert c.duration_days is None


def test_end_before_start_rejected(recipient):
    c = _treatment(recipient, start_date=date(2025, 2, 1), end_date=date(2025, 1, 1))
    with pytest.raises(ValidationError):
        c.clean()


# AC3 — IS changes classified directionally with optional CMV-management-intent tag


def test_change_direction_choices():
    field = MedicationCourse._meta.get_field("change_direction")
    assert {c[0] for c in field.choices} == {"reduction", "intensification"}


def test_change_direction_allowed_on_immunosuppressant(recipient):
    c = _treatment(recipient, change_direction="reduction", cmv_management_intent=True)
    c.full_clean()
    c.save()
    assert MedicationCourse.objects.get().change_direction == "reduction"


def test_change_direction_rejected_on_antiviral(recipient):
    c = _prophylaxis(recipient, change_direction="reduction")
    with pytest.raises(ValidationError):
        c.clean()


def test_cmv_management_intent_is_three_state(recipient):
    c = _treatment(recipient, cmv_management_intent=None)
    assert c.cmv_management_intent is None  # nullable: not tagged


def test_history_tracked(recipient):
    c = _prophylaxis(recipient, completed_per_protocol=True)
    c.save()
    assert c.history.count() == 1
