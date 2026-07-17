"""Slice 16b (issue #21) - the operational worklist-count tiles T2 (unverified
outcome-critical) and T3 (release-overdue QNAT). The load-bearing property: each
tile count is taken from the worklist's OWN queryset, so tile and worklist can
never disagree. Seam 1 (pure derivers over fixtures) + seam 2 (RBAC + agreement
through the admin test client).
"""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.test import Client
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from subay.registry.dashboard import release_overdue_count, unverified_count
from subay.registry.models import (
    CMVQuantitative,
    Recipient,
    RecipientVisit,
    RejectionEpisode,
)


# --- fixtures ---

def _recipient(subject_id="SCMVR21"):
    return Recipient.objects.create(
        subject_id=subject_id, date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=date(2025, 1, 1),
    )


def _unverified_rejection(recipient):
    # is_verified defaults False; the four-eyes gate only bites when True, so an
    # unverified row saves with no verifier - exactly a verification-worklist row.
    return RejectionEpisode.objects.create(
        recipient=recipient, onset_date=date(2025, 2, 1), rejection_type="tcmr",
    )


def _overdue_qnat(recipient, value="15000", drawn=date(2025, 4, 1)):
    # high viral load, no ReleaseEvent -> flagged release_overdue.
    visit = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_90", actual_visit_date=drawn,
    )
    return CMVQuantitative.objects.create(
        recipient_visit=visit, value=Decimal(value), severity_tier="asymptomatic",
        result_status="reported", drawn_date=drawn,
    )


# --- seam 1: pure derivers ---

@pytest.mark.django_db
def test_unverified_count_zero_when_none():
    assert unverified_count().count == 0


@pytest.mark.django_db
def test_unverified_count_tallies_unverified_rows():
    r = _recipient()
    _unverified_rejection(r)
    _unverified_rejection(r)
    tile = unverified_count()
    assert tile.count == 2
    assert tile.link == reverse("admin:verification_worklist")


@pytest.mark.django_db
def test_unverified_count_excludes_verified_rows():
    r = _recipient()
    row = _unverified_rejection(r)
    assert unverified_count().count == 1
    u1 = User.objects.create_user("enter")
    u2 = User.objects.create_user("verify")
    row.entered_by = u1
    row.verified_by = u2
    row.verified_at = date(2025, 2, 2)
    row.is_verified = True
    row.save()
    assert unverified_count().count == 0


@pytest.mark.django_db
def test_release_overdue_count_zero_when_none():
    assert release_overdue_count().count == 0


@pytest.mark.django_db
def test_release_overdue_count_tallies_flagged_qnat():
    r = _recipient()
    _overdue_qnat(r)
    tile = release_overdue_count()
    assert tile.count == 1
    assert tile.link == reverse("admin:safety_worklist")


# --- seam 2: RBAC + tile-vs-worklist agreement through the admin client ---

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


def _tile_keys(client):
    resp = client.get(reverse("admin:index"))
    assert resp.status_code == 200
    return [t.key for t in resp.context["dashboard_tiles"]]


@pytest.mark.django_db
def test_reviewing_clinician_sees_t2_not_t3():
    keys = _tile_keys(_otp_client(_group_user("doc", "reviewing_clinician")))
    assert "unverified" in keys
    assert "release_overdue" not in keys


@pytest.mark.django_db
def test_data_manager_sees_both_operational_tiles():
    keys = _tile_keys(_otp_client(_group_user("dm", "data_manager")))
    assert "unverified" in keys
    assert "release_overdue" in keys


@pytest.mark.django_db
def test_view_only_analyst_sees_neither_operational_tile():
    keys = _tile_keys(_otp_client(_group_user("ana", "data_analyst")))
    assert "unverified" not in keys
    assert "release_overdue" not in keys


@pytest.mark.django_db
def test_safety_monitor_perm_sees_t3_not_t2():
    # No dedicated safety-monitor Group exists; a principal holding only the
    # safety add permission (can-monitor-safety true, can-verify false) proves the
    # T3 gate is the perm, not a group name, and is independent of T2.
    user = User.objects.create_user("safety", "safety@x", "pw", is_staff=True)
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label="registry", codename="add_releaseevent")
    )
    keys = _tile_keys(_otp_client(user))
    assert "release_overdue" in keys
    assert "unverified" not in keys


@pytest.mark.django_db
def test_t2_count_matches_verification_worklist_total():
    r = _recipient()
    _unverified_rejection(r)
    _unverified_rejection(r)
    client = _otp_client(_group_user("doc", "reviewing_clinician"))
    index = client.get(reverse("admin:index"))
    tile = next(t for t in index.context["dashboard_tiles"] if t.key == "unverified")
    worklist = client.get(reverse("admin:verification_worklist"))
    assert tile.count == worklist.context["total"] == 2


@pytest.mark.django_db
def test_t3_count_matches_safety_worklist_total():
    r = _recipient()
    _overdue_qnat(r)
    client = _otp_client(_group_user("dm", "data_manager"))
    index = client.get(reverse("admin:index"))
    tile = next(t for t in index.context["dashboard_tiles"] if t.key == "release_overdue")
    worklist = client.get(reverse("admin:safety_worklist"))
    assert tile.count == worklist.context["total"] == 1
