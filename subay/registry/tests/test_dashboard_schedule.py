"""Slice 16c (issue #22) - T1 visits-due schedule synthesis. The one genuinely
new deriver: it reconstructs the expected six-timepoint schedule per still-enrolled
recipient (nothing in the app represents a not-yet-drawn visit), closure-shifts
each nominal day, and surfaces only the gaps. Seam 1 (pure deriver over fixtures,
`today` injected) + seam 2 (RBAC + read-only through the admin client).
"""
from datetime import date, timedelta

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from subay.registry.dashboard import DUE_SOON, MISSED, OVERDUE, visits_due
from subay.registry.models import (
    RECIPIENT_COMPLETION_STATUS_CHOICES,
    ClosureDay,
    Recipient,
    RecipientVisit,
)
from subay.registry.scheduling import TIMEPOINT_OFFSETS, VISIT_DUE_HORIZON_DAYS

TODAY = date(2025, 6, 1)


def _recipient(subject_id="SCMVR22", kt=None, status="enrolled"):
    return Recipient.objects.create(
        subject_id=subject_id, date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=kt or date(2025, 3, 1), completion_status=status,
    )


def _kt_placing(label, nominal):
    """kt_date that puts `label`'s nominal day on `nominal`."""
    return nominal - timedelta(days=TIMEPOINT_OFFSETS[label])


def _visit(recipient, label, when=None, status="completed"):
    return RecipientVisit.objects.create(
        recipient=recipient, timepoint_label=label,
        actual_visit_date=when or recipient.kt_date + timedelta(days=TIMEPOINT_OFFSETS[label]),
        completion_status=status,
    )


def _gap(tile, label):
    return next((g for g in tile.gaps if g.timepoint_label == label), None)


# --- seam 1: buckets ---

@pytest.mark.django_db
def test_due_soon_gap_within_horizon():
    _recipient(kt=_kt_placing("day_30", TODAY + timedelta(days=5)))
    gap = _gap(visits_due(today=TODAY), "day_30")
    assert gap is not None and gap.bucket == DUE_SOON


@pytest.mark.django_db
def test_overdue_gap_past_nominal_within_cap():
    _recipient(kt=_kt_placing("day_30", TODAY - timedelta(days=2)))
    gap = _gap(visits_due(today=TODAY), "day_30")
    assert gap is not None and gap.bucket == OVERDUE


@pytest.mark.django_db
def test_missed_gap_past_cap():
    _recipient(kt=_kt_placing("day_30", TODAY - timedelta(days=10)))
    gap = _gap(visits_due(today=TODAY), "day_30")
    assert gap is not None and gap.bucket == MISSED


@pytest.mark.django_db
def test_far_future_gap_not_surfaced():
    # nominal well beyond the horizon -> not yet actionable, no item.
    _recipient(kt=_kt_placing("day_30", TODAY + timedelta(days=30)))
    assert _gap(visits_due(today=TODAY), "day_30") is None


@pytest.mark.django_db
def test_entered_visit_never_appears():
    r = _recipient(kt=_kt_placing("day_30", TODAY - timedelta(days=2)))  # would be overdue
    _visit(r, "day_30")
    assert _gap(visits_due(today=TODAY), "day_30") is None


# --- seam 1: enrolled-only active filter ---

@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [v for v, _ in RECIPIENT_COMPLETION_STATUS_CHOICES if v != "enrolled"],
)
def test_non_enrolled_disposition_yields_zero_items(status):
    _recipient(kt=_kt_placing("day_30", TODAY - timedelta(days=2)), status=status)
    assert visits_due(today=TODAY).total == 0


@pytest.mark.django_db
def test_visit_level_missed_visit_still_surfaces_rest_of_timeline():
    r = _recipient(kt=_kt_placing("day_30", TODAY - timedelta(days=2)))
    # one visit-level missed_visit does NOT change the patient disposition.
    _visit(r, "day_7", status="missed_visit")
    tile = visits_due(today=TODAY)
    assert _gap(tile, "day_7") is None          # that timepoint now has a row
    assert _gap(tile, "day_30") is not None      # the rest of the timeline still shows
    assert r.completion_status == "enrolled"


# --- seam 1: closure-shift moves the bucket boundary ---

@pytest.mark.django_db
def test_closure_shift_pushes_edge_gap_out_of_horizon():
    # nominal lands exactly on the horizon edge -> due-soon without a closure.
    _recipient(kt=_kt_placing("day_30", TODAY + timedelta(days=VISIT_DUE_HORIZON_DAYS)))
    assert _gap(visits_due(today=TODAY), "day_30").bucket == DUE_SOON
    # a closure on that edge day shifts the expected date one past the horizon.
    ClosureDay.objects.create(
        date=TODAY + timedelta(days=VISIT_DUE_HORIZON_DAYS), reason="annexed_holiday",
    )
    assert _gap(visits_due(today=TODAY), "day_30") is None


# --- seam 1: deep-link + read-only ---

@pytest.mark.django_db
def test_gap_deep_links_to_prefilled_add_form():
    r = _recipient(kt=_kt_placing("day_30", TODAY - timedelta(days=2)))
    gap = _gap(visits_due(today=TODAY), "day_30")
    add_base = reverse("admin:registry_recipientvisit_add")
    assert gap.add_url.startswith(add_base)
    assert f"recipient={r.pk}" in gap.add_url
    assert "timepoint_label=day_30" in gap.add_url
    assert f"actual_visit_date={gap.expected_date.isoformat()}" in gap.add_url
    assert gap.subject_id == r.subject_id


@pytest.mark.django_db
def test_deriver_writes_nothing():
    _recipient(kt=_kt_placing("day_30", TODAY - timedelta(days=2)))
    before_v = RecipientVisit.objects.count()
    before_r = Recipient.objects.count()
    visits_due(today=TODAY)
    assert RecipientVisit.objects.count() == before_v
    assert Recipient.objects.count() == before_r


def test_horizon_is_a_named_constant():
    assert VISIT_DUE_HORIZON_DAYS == 7


# --- seam 2: RBAC through the admin client ---

def _otp_client(user):
    device = TOTPDevice.objects.create(user=user, name="test", confirmed=True)
    client = Client()
    client.force_login(user)
    session = client.session
    session["otp_device_id"] = device.persistent_id
    session.save()
    return client


def _group_user(username, group_name):
    user = User.objects.create_user(username, f"{username}@x", "pw", is_staff=True)
    user.groups.add(Group.objects.get(name=group_name))
    return user


def _tile_keys(user):
    resp = _otp_client(user).get(reverse("admin:index"))
    assert resp.status_code == 200
    return [t.key for t in resp.context["dashboard_tiles"]]


@pytest.mark.django_db
def test_data_manager_with_add_recipientvisit_sees_t1():
    assert "visits_due" in _tile_keys(_group_user("dm", "data_manager"))


@pytest.mark.django_db
def test_view_only_analyst_never_sees_t1():
    assert "visits_due" not in _tile_keys(_group_user("ana", "data_analyst"))
