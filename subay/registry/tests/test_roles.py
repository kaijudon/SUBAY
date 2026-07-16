"""Slice 13 - the finalized role model (US 66/67) and the AC4 cross-cutting
guarantees (OTP on every role, django-simple-history on the verified models).

Roles are PURE Django Groups/Permissions (AC3): the four groups come from
migration 0002 and their RBAC matrix from migration 0019, with no bespoke
security framework. These tests characterize that shipped contract so a future
edit cannot silently widen a role or drop the OTP/history guarantees.
"""
import pytest
from django.contrib.auth.models import Group, Permission
from django_otp.admin import OTPAdminSite

from subay.registry.models import CMVSerology, DrugLevel, GenotypeCall, RejectionEpisode
from subay.registry.sites import SubayAdminSite

# The four outcome-critical (four-eyes) models: the only ones a reviewing
# clinician is granted change on, and the set the verification mixin attaches to.
OUTCOME_CRITICAL = ["cmvserology", "druglevel", "rejectionepisode", "genotypecall"]

ROLE_NAMES = {"data_manager", "reviewing_clinician", "data_analyst", "admin"}


def _codenames(group_name):
    """The registry-app permission codenames granted to one role Group."""
    return set(
        Group.objects.get(name=group_name)
        .permissions.filter(content_type__app_label="registry")
        .values_list("codename", flat=True)
    )


def _registry_codenames(prefix):
    """Every registry codename for one action verb, e.g. all `view_*`."""
    return set(
        Permission.objects.filter(
            content_type__app_label="registry", codename__startswith=f"{prefix}_"
        ).values_list("codename", flat=True)
    )


# --- AC3: roles exist purely as Django Groups/Permissions ---


@pytest.mark.django_db
def test_four_role_groups_exist():
    names = set(Group.objects.values_list("name", flat=True))
    assert ROLE_NAMES <= names


@pytest.mark.django_db
def test_admin_role_holds_every_registry_permission():
    reg = set(
        Permission.objects.filter(content_type__app_label="registry")
        .values_list("codename", flat=True)
    )
    assert _codenames("admin") == reg


@pytest.mark.django_db
def test_data_manager_is_add_change_view_but_never_delete():
    """The entry role edits everything but deletes nothing - delete is governed
    by the append-only admin mixins, so no delete perm is granted (0019)."""
    got = _codenames("data_manager")
    assert got == (
        _registry_codenames("add")
        | _registry_codenames("change")
        | _registry_codenames("view")
    )
    assert not any(c.startswith("delete_") for c in got)


@pytest.mark.django_db
def test_data_analyst_is_view_only():
    got = _codenames("data_analyst")
    assert got == _registry_codenames("view")
    assert all(c.startswith("view_") for c in got)


@pytest.mark.django_db
def test_reviewing_clinician_is_view_plus_change_on_outcome_critical_only():
    """Read everything, but change only the four-eyes models so it can verify -
    no add, no delete, no change on non-outcome-critical rows."""
    got = _codenames("reviewing_clinician")
    expected_change = {f"change_{m}" for m in OUTCOME_CRITICAL}
    assert got == _registry_codenames("view") | expected_change
    assert not any(c.startswith(("add_", "delete_")) for c in got)


# --- AC4: OTP on every role; simple-history on the verified models ---


def test_admin_site_enforces_otp_for_every_role():
    """The sole data-entry interface subclasses OTPAdminSite, so TOTP 2FA gates
    every login regardless of Group - there is no non-OTP admin route."""
    assert issubclass(SubayAdminSite, OTPAdminSite)


@pytest.mark.parametrize("model", [CMVSerology, DrugLevel, RejectionEpisode, GenotypeCall])
def test_verified_models_record_history(model):
    """Every outcome-critical model carries a simple-history shadow table so a
    verify (or any change) is auditable."""
    assert hasattr(model, "history")
    assert model.history.model.__name__.startswith("Historical")
