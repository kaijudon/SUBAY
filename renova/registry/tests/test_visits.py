"""AC1-3,5,6,7 — RecipientVisit spine, closure-shift derivation, +3-cap
validator, and the minimal DonorVisit record.

Derived values (`nominal_day`, `closure_*`, `shift_days_from_nominal`) are
`@property`, never stored columns — the tests assert they are absent from the
model's field list, so a stored fact and its computed value can never drift.
"""
from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError

from renova.registry.models import (
    ClosureDay,
    CMVSerology,
    Donor,
    DonorVisit,
    Recipient,
    RecipientVisit,
)


@pytest.fixture
def recipient(db):
    return Recipient.objects.create(
        subject_id="SCMVR07",
        date_of_birth=date(1980, 1, 1),
        sex="M",
        kt_date=date(2025, 1, 1),
    )


def _field_names(model):
    return [f.name for f in model._meta.get_fields()]


# --- AC1: six timepoints, nominal_day computed from kt_date + offset ---

def test_six_timepoints_have_computed_nominal_day(recipient):
    expected = {"pre_kt": 0, "day_7": 7, "day_30": 30, "day_90": 90,
                "day_120": 120, "day_180": 180}
    for label, offset in expected.items():
        v = RecipientVisit.objects.create(
            recipient=recipient,
            timepoint_label=label,
            actual_visit_date=recipient.kt_date + timedelta(days=offset),
        )
        assert v.nominal_day == offset
        assert v.nominal_date == recipient.kt_date + timedelta(days=offset)


def test_nominal_day_is_derived_not_stored(recipient):
    assert "nominal_day" not in _field_names(RecipientVisit)
    assert "shift_days_from_nominal" not in _field_names(RecipientVisit)
    assert "closure_shifted" not in _field_names(RecipientVisit)
    assert "closure_reason" not in _field_names(RecipientVisit)


# --- AC2: both nominal_day and actual_visit_date; timepoint_label is join key ---

def test_visit_exposes_both_nominal_and_actual(recipient):
    v = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_7",
        actual_visit_date=date(2025, 1, 8),
    )
    assert v.nominal_day == 7
    assert v.actual_visit_date == date(2025, 1, 8)


def test_timepoint_label_is_the_lab_join_key(recipient):
    """The join key is the label string, not the raw actual day — two visits
    on different recipients share the label. CMVSerology still attaches."""
    other = Recipient.objects.create(
        subject_id="SCMVR08", date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=date(2025, 6, 1),
    )
    v1 = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_30",
        actual_visit_date=date(2025, 1, 31),
    )
    v2 = RecipientVisit.objects.create(
        recipient=other, timepoint_label="day_30",
        actual_visit_date=date(2025, 7, 5),
    )
    assert v1.timepoint_label == v2.timepoint_label == "day_30"
    from decimal import Decimal
    s = CMVSerology.objects.create(
        recipient_visit=v1, value=Decimal("3.0"), drawn_date=date(2025, 1, 31)
    )
    assert s.recipient_visit == v1


# --- AC3: closure day -> forward shift, with reason + reference ---

def test_closure_on_nominal_shifts_forward_with_reason_and_reference(recipient):
    # day_7 nominal = 2025-01-08; close it.
    ClosureDay.objects.create(
        date=date(2025, 1, 8), reason="annexed_holiday",
        reference="Annex A clause 3",
    )
    v = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_7",
        actual_visit_date=date(2025, 1, 9),
    )
    assert v.scheduled_date == date(2025, 1, 9)
    assert v.closure_shifted is True
    assert v.closure_reason == "annexed_holiday"
    assert v.stretch_reference == "Annex A clause 3"


def test_no_closure_means_not_shifted(recipient):
    v = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_7",
        actual_visit_date=date(2025, 1, 8),
    )
    assert v.scheduled_date == v.nominal_date
    assert v.closure_shifted is False
    assert v.closure_reason == "none"
    assert v.stretch_reference == ""


# --- AC5: actual > +3 days rejected, forces missed_visit ---

def test_actual_within_cap_saves_as_normal_visit(recipient):
    # +3 is the boundary — still legal.
    v = RecipientVisit(
        recipient=recipient, timepoint_label="day_7",
        actual_visit_date=recipient.kt_date + timedelta(days=7 + 3),
        completion_status="completed",
    )
    v.full_clean()  # must not raise


def test_actual_beyond_cap_rejected_when_completed(recipient):
    v = RecipientVisit(
        recipient=recipient, timepoint_label="day_7",
        actual_visit_date=recipient.kt_date + timedelta(days=7 + 4),
        completion_status="completed",
    )
    with pytest.raises(ValidationError):
        v.full_clean()


def test_actual_beyond_cap_saves_when_marked_missed(recipient):
    v = RecipientVisit(
        recipient=recipient, timepoint_label="day_7",
        actual_visit_date=recipient.kt_date + timedelta(days=7 + 4),
        completion_status="missed_visit",
    )
    v.full_clean()  # the only legal way to persist a beyond-cap actual
    v.save()
    assert RecipientVisit.objects.count() == 1


# --- AC6: shift_days_from_nominal derived, separates forced vs non-attendance ---

def test_shift_days_distinguishes_closure_from_no_show(recipient):
    # Forced replacement: a closure pushed the visit out.
    ClosureDay.objects.create(date=date(2025, 1, 8), reason="emergency_closure",
                              reference="Memo 12")
    forced = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_7",
        actual_visit_date=date(2025, 1, 10),
    )
    # Patient no-show: no closure, just a late actual within cap.
    no_show = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_30",
        actual_visit_date=recipient.kt_date + timedelta(days=30 + 2),
    )
    assert forced.shift_days_from_nominal == 2  # 2025-01-10 minus 2025-01-08
    assert forced.closure_reason == "emergency_closure"
    assert no_show.shift_days_from_nominal == 2
    assert no_show.closure_reason == "none"
    # The pair (shift, reason) separates the two CONSORT categories.
    assert (forced.shift_days_from_nominal, forced.closure_reason) != (
        no_show.shift_days_from_nominal, no_show.closure_reason
    )


def test_shift_days_is_derived_not_stored(recipient):
    assert "shift_days_from_nominal" not in _field_names(RecipientVisit)


# --- AC7: DonorVisit minimal donor + draw_date, no recipient-grade timeline ---

def test_donor_visit_is_minimal_record(db):
    d = Donor.objects.create(subject_id="DCMVD01", date_of_birth=date(1975, 1, 1), sex="F")
    dv = DonorVisit.objects.create(donor=d, draw_date=date(2024, 12, 1))
    assert dv.donor == d
    assert dv.draw_date == date(2024, 12, 1)


def test_donor_visit_has_no_recipient_grade_timeline():
    fields = _field_names(DonorVisit)
    for forbidden in ("nominal_day", "timepoint_label", "closure_shifted",
                      "closure_reason", "shift_days_from_nominal", "actual_visit_date"):
        assert forbidden not in fields
    assert not hasattr(DonorVisit, "nominal_day")
    assert not hasattr(DonorVisit, "scheduled_date")
