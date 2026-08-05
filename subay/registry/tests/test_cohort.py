"""Slice 04 — completer-cohort accounting on Recipient + result-level missing
observation on CMVSerology. The load-bearing test is the last one: an external
lab failure must never flip a patient's cohort disposition."""
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count

from subay.registry.models import (
    RECIPIENT_COMPLETION_STATUS_CHOICES,
    CMVSerology,
    Recipient,
    RecipientVisit,
)

SEVEN_LOCKED = {
    "enrolled",
    "withdrawn",
    "died",
    "lost_to_followup",
    "graft_loss",
    "missed_visit",
    "completed",
}


def _recipient(subject_id, status="enrolled"):
    return Recipient.objects.create(
        subject_id=subject_id,
        date_of_birth=date(1980, 1, 1),
        sex="M",
        kt_date=date(2025, 1, 1),
        completion_status=status,
    )


# --- AC1: the seven-value enum drives a reproducible CONSORT count ---


def test_completion_status_has_seven_locked_values(db):
    field = Recipient._meta.get_field("completion_status")
    assert {value for value, _label in field.choices} == SEVEN_LOCKED
    assert field.default == "enrolled"


def test_consort_count_is_reproducible_from_db(db):
    _recipient("SCMVR01", "completed")
    _recipient("SCMVR02", "completed")
    _recipient("SCMVR03", "withdrawn")
    _recipient("SCMVR04", "died")

    counts = {
        row["completion_status"]: row["n"]
        for row in Recipient.objects.values("completion_status").annotate(n=Count("pk"))
    }
    assert counts == {"completed": 2, "withdrawn": 1, "died": 1}


# --- AC2: a lab/QC failure is a missing observation on the result ---


def test_lab_failure_is_missing_observation_on_result(db):
    r = _recipient("SCMVR01", "completed")
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8)
    )
    s = CMVSerology(recipient_visit=v, result_status="missing", drawn_date=date(2025, 1, 8))
    s.full_clean()
    s.save()

    s.refresh_from_db()
    assert s.value is None
    assert s.igg_interpretation is None  # was is_positive, retired in slice 17
    assert s.result_status == "missing"


def test_missing_observation_must_not_carry_a_value(db):
    r = _recipient("SCMVR01", "completed")
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8)
    )
    s = CMVSerology(
        recipient_visit=v, result_status="missing", value=Decimal("3.0"), drawn_date=date(2025, 1, 8)
    )
    with pytest.raises(ValidationError):
        s.full_clean()
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            s.save()


def test_reported_result_must_carry_a_value(db):
    r = _recipient("SCMVR01", "completed")
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8)
    )
    s = CMVSerology(recipient_visit=v, result_status="reported", drawn_date=date(2025, 1, 8))
    with pytest.raises(ValidationError):
        s.full_clean()
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            s.save()


# --- AC3: non-completer samples stay queryable and flagged for sequencing ---


def test_non_completer_samples_remain_queryable_and_flagged(db):
    r = _recipient("SCMVR01", "withdrawn")
    assert r.sequencing_included is True  # default: in the all-sequenced denominator
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8)
    )
    CMVSerology.objects.create(recipient_visit=v, value=Decimal("3.0"), drawn_date=date(2025, 1, 8))

    queried = CMVSerology.objects.filter(recipient_visit__recipient=r)
    assert queried.count() == 1


# --- AC5 (load-bearing): a lab failure does NOT flip completion_status ---


def test_lab_failure_does_not_flip_completion_status(db):
    r = _recipient("SCMVR01", "completed")
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8)
    )
    CMVSerology.objects.create(
        recipient_visit=v, result_status="missing", drawn_date=date(2025, 1, 8)
    )

    r.refresh_from_db()
    assert r.completion_status == "completed"
