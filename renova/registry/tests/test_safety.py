"""Slice 14 — Safety release-timeliness surface (US 71, 72).

A standing query flags any recipient-attached, REPORTED `CMVQuantitative` that is
high-viral-load (>= 10,000 IU/mL) OR symptomatic (severity_tier in syndrome/disease)
with no `ReleaseEvent` logged inside the 24h window → surfaced to the Safety Monitor.
A timely release clears the flag; a late one does not. A missed/late release is
recordable as a `ProtocolDeviation`, and additionally as a research-related SAE when
it caused harm (dual-track, one model two booleans). The threshold, the window, and
the symptomatic tiers are named constants in the discoverable `safety.py` so they
can never be hard-coded magic. The flag is derived from stored rows (no manual list).
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import models

from renova.registry.episodes import SEVERITY_TIERS
from renova.registry.safety import (
    RELEASE_THRESHOLD_IU_ML,
    RELEASE_WINDOW,
    RELEASE_WINDOW_DAYS,
    SYMPTOMATIC_TIERS,
    is_release_timely,
    requires_release,
)
from renova.registry.models import (
    DEVIATION_TYPE_CHOICES,
    CMVQuantitative,
    ProtocolDeviation,
    Recipient,
    RecipientVisit,
    ReleaseEvent,
)


# --- Step 1: pure module safety.py (no DB) — AC1/AC2 constants & predicates ---


def test_constants_are_named_and_explicit():
    assert RELEASE_THRESHOLD_IU_ML == Decimal("10000")
    assert RELEASE_WINDOW == timedelta(hours=24)
    assert RELEASE_WINDOW_DAYS == 1


def test_symptomatic_tiers_cannot_drift_from_episodes():
    assert SYMPTOMATIC_TIERS == ("syndrome", "disease")
    assert SYMPTOMATIC_TIERS == tuple(t for t in SEVERITY_TIERS if t != "asymptomatic")


@pytest.mark.parametrize(
    "value,tier,expected",
    [
        (Decimal("15000"), "asymptomatic", True),   # high value alone triggers
        (Decimal("34.5"), "syndrome", True),        # symptomatic alone triggers
        (Decimal("34.5"), "asymptomatic", False),   # below + asymptomatic -> no
        (Decimal("10000"), "asymptomatic", True),   # boundary, inclusive (>=)
        (None, "disease", True),                     # symptomatic, no value, still triggers
        (None, "asymptomatic", False),
    ],
)
def test_requires_release_truth_table(value, tier, expected):
    assert requires_release(value, tier) is expected


@pytest.mark.parametrize(
    "drawn,released_offsets,expected",
    [
        (0, [0], True),     # same-day
        (0, [1], True),     # next-day, inside the window
        (0, [2], False),    # two days late
        (0, [-1], False),   # released before the draw
        (0, [], False),     # no release at all
        (5, [5, 6], True),  # any release inside the window is enough
    ],
)
def test_is_release_timely_truth_table(drawn, released_offsets, expected):
    assert is_release_timely(drawn, released_offsets, RELEASE_WINDOW_DAYS) is expected


# --- Steps 2 & 3: ReleaseEvent + ProtocolDeviation models ---


@pytest.fixture
def recipient(db):
    return Recipient.objects.create(
        subject_id="SCMVR14", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )


def _qnat(recipient, value=None, tier="asymptomatic", drawn=date(2025, 4, 1), status="reported"):
    v = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_90", actual_visit_date=drawn
    )
    return CMVQuantitative.objects.create(
        recipient_visit=v,
        value=Decimal(value) if value is not None else None,
        severity_tier=tier,
        result_status=status,
        drawn_date=drawn,
    )


def test_release_event_saves_with_reverse_accessor(recipient):
    q = _qnat(recipient, value="15000")
    e = ReleaseEvent.objects.create(quantitative=q, released_date=date(2025, 4, 1))
    assert list(q.release_events.all()) == [e]


def test_release_event_cannot_predate_draw(recipient):
    q = _qnat(recipient, value="15000")
    e = ReleaseEvent(quantitative=q, released_date=date(2025, 3, 31))  # before drawn_date
    with pytest.raises(ValidationError):
        e.full_clean()


def test_release_event_fk_is_cascade(recipient):
    q = _qnat(recipient, value="15000")
    ReleaseEvent.objects.create(quantitative=q, released_date=date(2025, 4, 1))
    assert ReleaseEvent._meta.get_field("quantitative").remote_field.on_delete is models.CASCADE
    q.delete()
    assert ReleaseEvent.objects.count() == 0


def test_derived_flags_are_properties_not_stored():
    field_names = {f.name for f in CMVQuantitative._meta.get_fields()}
    for name in ("requires_release", "has_timely_release", "release_overdue"):
        assert name not in field_names
        assert isinstance(getattr(CMVQuantitative, name), property)


def test_high_value_with_no_release_is_overdue(recipient):
    q = _qnat(recipient, value="15000")
    assert q.requires_release is True
    assert q.release_overdue is True


def test_symptomatic_with_no_release_is_overdue(recipient):
    q = _qnat(recipient, value="34.5", tier="disease")
    assert q.release_overdue is True


def test_below_threshold_asymptomatic_is_not_overdue(recipient):
    q = _qnat(recipient, value="34.5", tier="asymptomatic")
    assert q.requires_release is False
    assert q.release_overdue is False


def test_timely_release_clears_the_flag(recipient):
    q = _qnat(recipient, value="15000")
    ReleaseEvent.objects.create(quantitative=q, released_date=date(2025, 4, 2))  # next-day
    assert q.has_timely_release is True
    assert q.release_overdue is False


def test_late_release_does_not_clear_the_flag(recipient):
    q = _qnat(recipient, value="15000")
    ReleaseEvent.objects.create(quantitative=q, released_date=date(2025, 4, 5))  # 4 days late
    assert q.has_timely_release is False
    assert q.release_overdue is True


def test_missing_result_is_never_overdue(recipient):
    # A QC/lab failure (no value) is not an actionable result, even if symptomatic.
    q = _qnat(recipient, value=None, tier="disease", status="missing")
    assert q.release_overdue is False


# --- AC1/AC4: the standing query, reproducible from stored rows ---


def test_overdue_release_flags_returns_exactly_overdue_reported_recipient_draws(recipient):
    overdue_high = _qnat(recipient, value="20000")
    overdue_symptom = _qnat(recipient, value="50", tier="syndrome")
    cleared = _qnat(recipient, value="15000")
    ReleaseEvent.objects.create(quantitative=cleared, released_date=date(2025, 4, 1))
    _qnat(recipient, value="34.5", tier="asymptomatic")  # below + asymptomatic -> not flagged
    flagged = set(CMVQuantitative.objects.overdue_release_flags())
    assert flagged == {overdue_high, overdue_symptom}


def test_overdue_flags_exclude_donor_attached_qnat(db):
    from renova.registry.models import Donor

    d = Donor.objects.create(
        subject_id="DCMVD14", date_of_birth=date(1980, 1, 1), sex="M", donor_type="living"
    )
    CMVQuantitative.objects.create(
        donor=d, value=Decimal("99999"), result_status="reported", drawn_date=date(2025, 4, 1)
    )
    # No kt anchor -> never a standing-query flag (mirrors _reported_qnat_points).
    assert list(CMVQuantitative.objects.overdue_release_flags()) == []


# --- AC3: dual-track deviation / SAE ---


def test_deviation_type_choices_are_late_or_missed():
    assert {c for c, _ in DEVIATION_TYPE_CHOICES} == {"late_release", "missed_release"}


def test_deviation_only_row_is_valid(recipient):
    q = _qnat(recipient, value="15000")
    dev = ProtocolDeviation(
        quantitative=q, deviation_type="missed_release",
        caused_harm=False, is_research_related_sae=False,
    )
    dev.full_clean()  # no error
    dev.save()
    assert q.protocol_deviations.count() == 1


def test_sae_with_harm_is_valid_and_both_tracks_countable(recipient):
    q = _qnat(recipient, value="15000")
    dev = ProtocolDeviation(
        quantitative=q, deviation_type="late_release",
        caused_harm=True, is_research_related_sae=True,
    )
    dev.full_clean()
    dev.save()
    assert ProtocolDeviation.objects.filter(is_research_related_sae=True).count() == 1
    assert ProtocolDeviation.objects.filter(caused_harm=True).count() == 1


def test_sae_without_harm_is_rejected(recipient):
    q = _qnat(recipient, value="15000")
    dev = ProtocolDeviation(
        quantitative=q, deviation_type="late_release",
        caused_harm=False, is_research_related_sae=True,
    )
    with pytest.raises(ValidationError):
        dev.full_clean()


def test_deviation_fk_is_cascade_and_recipient_through_tube(recipient):
    q = _qnat(recipient, value="15000")
    dev = ProtocolDeviation.objects.create(quantitative=q, deviation_type="missed_release")
    assert dev.recipient.subject_id == "SCMVR14"
    assert ProtocolDeviation._meta.get_field("quantitative").remote_field.on_delete is models.CASCADE
    q.delete()
    assert ProtocolDeviation.objects.count() == 0


# --- History (consistency with every prior outcome model) ---


def test_history_tracked(recipient):
    q = _qnat(recipient, value="15000")
    e = ReleaseEvent.objects.create(quantitative=q, released_date=date(2025, 4, 1))
    assert e.history.count() == 1
    dev = ProtocolDeviation.objects.create(quantitative=q, deviation_type="late_release")
    assert dev.history.count() == 1
