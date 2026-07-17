"""Slice 16a (issue #20) - the admin-index dashboard panel, driven through the
real admin test client. Mirrors test_admin_index.py: OTPAdminSite needs an
OTP-verified session, so each helper attaches a confirmed TOTP device the way
django-otp's middleware expects. Asserts which tiles a given role sees - the
externally observable RBAC behavior - not template markup internals.
"""
from datetime import date

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.test import Client
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from subay.registry.models import Recipient

CONSORT_MARKER = "subay-dashboard"


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


def _index(user):
    resp = _otp_client(user).get(reverse("admin:index"))
    assert resp.status_code == 200  # OTP-verified, not bounced to login
    return resp


def _recipient(subject_id, status="enrolled"):
    return Recipient.objects.create(
        subject_id=subject_id,
        date_of_birth=date(1980, 1, 1),
        sex="M",
        kt_date=date(2025, 1, 1),
        completion_status=status,
    )


@pytest.mark.django_db
def test_superuser_sees_consort_tile():
    user = User.objects.create_superuser("root", "root@x", "pw")
    resp = _index(user)
    keys = [t.key for t in resp.context["dashboard_tiles"]]
    # a superuser holds every gated permission, so the CONSORT tile is present
    # among the tiles it can act on.
    assert "consort" in keys
    assert CONSORT_MARKER in resp.content.decode()


@pytest.mark.django_db
def test_role_with_view_recipient_sees_the_tile():
    # data_analyst is granted view on every registry model (migration 0019).
    resp = _index(_group_user("ana", "data_analyst"))
    assert [t.key for t in resp.context["dashboard_tiles"]] == ["consort"]


@pytest.mark.django_db
def test_role_without_view_recipient_sees_no_panel():
    # A plain staff user with no group holds none of the gated permissions, so
    # the whole dashboard panel is omitted (no empty box).
    user = User.objects.create_user("nobody", "nobody@x", "pw", is_staff=True)
    resp = _index(user)
    assert resp.context["dashboard_tiles"] == []
    assert CONSORT_MARKER not in resp.content.decode()


@pytest.mark.django_db
def test_tile_gate_is_the_view_recipient_perm_not_a_group_name():
    # Grant only view_recipient directly (no role Group): the tile still shows,
    # proving the gate is the perm, not a hardcoded group.
    user = User.objects.create_user("direct", "direct@x", "pw", is_staff=True)
    user.user_permissions.add(
        Permission.objects.get(content_type__app_label="registry", codename="view_recipient")
    )
    resp = _index(user)
    assert [t.key for t in resp.context["dashboard_tiles"]] == ["consort"]


@pytest.mark.django_db
def test_counts_render_in_the_panel():
    _recipient("SCMVR01", "enrolled")
    _recipient("SCMVR02", "withdrawn")
    user = User.objects.create_superuser("root", "root@x", "pw")
    resp = _index(user)
    tile = next(t for t in resp.context["dashboard_tiles"] if t.key == "consort")
    assert tile.total == 2
    body = resp.content.decode()
    assert "Enrolled" in body and "Withdrawn" in body
