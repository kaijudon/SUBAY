"""Front-end 3 (issue #3): the grouped, role-scoped admin index.

Driven through the real admin test client. OTPAdminSite requires an OTP-verified
session, so each helper attaches a confirmed TOTP device to the session the way
django-otp's middleware expects — otherwise every admin page 302s to login.
"""
import pytest
from django.contrib.auth.models import Group, User
from django.test import Client
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

# Study workflow order the index must present (Administration trails for the
# auth/otp management models a superuser can reach).
WORK_ORDER = ["Subjects", "Visit spine", "Labs", "Biobank ledger", "Genotyping", "Safety"]


def _otp_client(user):
    """A logged-in, OTP-verified client for `user`."""
    device = TOTPDevice.objects.create(user=user, name="test", confirmed=True)
    client = Client()
    client.force_login(user)
    session = client.session
    session["otp_device_id"] = device.persistent_id
    session.save()
    return client


def _role_user(username, group_name=None, superuser=False):
    if superuser:
        return User.objects.create_superuser(username, f"{username}@x", "pw")
    user = User.objects.create_user(username, f"{username}@x", "pw", is_staff=True)
    if group_name:
        user.groups.add(Group.objects.get(name=group_name))
    return user


def _app_list(user):
    resp = _otp_client(user).get(reverse("admin:index"))
    assert resp.status_code == 200  # OTP-verified, not bounced to login
    return resp.context["app_list"]


def _section(app_list, name):
    return next((a for a in app_list if a["name"] == name), None)


@pytest.mark.django_db
def test_index_grouped_in_study_work_order():
    app_list = _app_list(_role_user("root", superuser=True))
    names = [a["name"] for a in app_list]
    # the six workflow sections come first, in work order
    assert names[: len(WORK_ORDER)] == WORK_ORDER
    # models sit in the section they belong to, not a flat alphabetical wall
    subjects = {m["object_name"] for m in _section(app_list, "Subjects")["models"]}
    assert subjects == {"Recipient", "Donor"}
    safety = {m["object_name"] for m in _section(app_list, "Safety")["models"]}
    assert safety == {"ReleaseEvent", "ProtocolDeviation"}


@pytest.mark.django_db
def test_labs_section_within_work_order_not_alphabetical():
    app_list = _app_list(_role_user("root", superuser=True))
    labs = [m["object_name"] for m in _section(app_list, "Labs")["models"]]
    # CMVSerology leads (work order), even though it is not first alphabetically
    assert labs[0] == "CMVSerology"


@pytest.mark.django_db
def test_data_analyst_is_read_only_everywhere():
    app_list = _app_list(_role_user("ana", "data_analyst"))
    assert app_list  # analyst can view, so sections show
    for app in app_list:
        for model in app["models"]:
            assert model["perms"]["view"] is True
            assert model["perms"]["add"] is False
            assert model["perms"]["change"] is False
            assert model["perms"]["delete"] is False


@pytest.mark.django_db
def test_reviewing_clinician_changes_only_outcome_critical():
    app_list = _app_list(_role_user("doc", "reviewing_clinician"))

    def perms_for(object_name):
        for app in app_list:
            for m in app["models"]:
                if m["object_name"] == object_name:
                    return m["perms"]
        return None

    # can verify (change) an outcome-critical row...
    assert perms_for("CMVSerology")["change"] is True
    # ...but not mutate the subject spine
    assert perms_for("Recipient")["change"] is False
    assert perms_for("Recipient")["view"] is True


@pytest.mark.django_db
def test_data_manager_enters_but_cannot_delete():
    app_list = _app_list(_role_user("dm", "data_manager"))

    def perms_for(object_name):
        for app in app_list:
            for m in app["models"]:
                if m["object_name"] == object_name:
                    return m["perms"]
        return None

    rec = perms_for("Recipient")
    assert rec["add"] is True and rec["change"] is True and rec["view"] is True
    assert rec["delete"] is False


@pytest.mark.django_db
def test_index_shows_only_sections_the_group_can_act_on():
    """A group scoped to only the Safety models sees only the Safety section —
    empty sections are not emitted, so the landing is scoped to the job."""
    from django.contrib.auth.models import Permission

    grp = Group.objects.create(name="safety_only")
    grp.permissions.set(
        Permission.objects.filter(
            content_type__app_label="registry",
            codename__in=["view_releaseevent", "view_protocoldeviation"],
        )
    )
    user = User.objects.create_user("mon", "mon@x", "pw", is_staff=True)
    user.groups.add(grp)

    names = [a["name"] for a in _app_list(user)]
    assert names == ["Safety"]


@pytest.mark.django_db
def test_no_model_moved_between_apps():
    """Grouping is site-level presentation: every registry model still reports
    registry as its Django app_label."""
    from django.contrib import admin
    from renova.registry.models import Recipient, ReleaseEvent

    assert Recipient._meta.app_label == "registry"
    assert ReleaseEvent._meta.app_label == "registry"
    # and the models are still registered on the site
    assert Recipient in admin.site._registry
