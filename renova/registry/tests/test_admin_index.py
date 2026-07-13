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
def test_visit_change_page_renders_with_autocomplete_and_inline_derived_flags():
    """Front-end 2 (#4) smoke: the visit change page (autocomplete FKs +
    lab inlines carrying derived read-only flags) renders through the client."""
    from datetime import date
    from decimal import Decimal
    from renova.registry.models import (
        CMVQuantitative, CMVSerology, Recipient, RecipientVisit, RenalFunction,
    )

    rec = Recipient.objects.create(
        subject_id="SCMVR30", date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=date(2025, 1, 1),
    )
    visit = RecipientVisit.objects.create(
        recipient=rec, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8),
    )
    CMVSerology.objects.create(
        recipient_visit=visit, value=Decimal("3.0"), drawn_date=date(2025, 1, 8),
    )
    CMVQuantitative.objects.create(
        recipient_visit=visit, value=Decimal("50000"), drawn_date=date(2025, 1, 8),
    )
    RenalFunction.objects.create(
        recipient_visit=visit, serum_creatinine_mg_dl=Decimal("1.2"),
        drawn_date=date(2025, 1, 8),
    )

    client = _otp_client(_role_user("root", superuser=True))
    resp = client.get(reverse("admin:registry_recipientvisit_change", args=[visit.pk]))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_lab_changelist_renders_through_client():
    from renova.registry.models import DrugLevel

    client = _otp_client(_role_user("root", superuser=True))
    resp = client.get(reverse("admin:registry_druglevel_changelist"))
    assert resp.status_code == 200
    assert DrugLevel._meta.app_label == "registry"


# --- Front-end 4 (issue #5): Reviewing Clinician verification worklist ---

WORKLIST_URL = "/admin/verification-worklist/"


def _seed_outcome_critical(editor, verifier):
    """One unverified row per outcome-critical model, plus one fully-verified
    CMVSerology that the worklist must EXCLUDE. Returns the unverified serology."""
    from datetime import date
    from decimal import Decimal
    from renova.registry.models import (
        Aliquot, CMVSerology, DrugLevel, GenotypeCall, GenotypingResult,
        PipelineRun, Recipient, RecipientVisit, RejectionEpisode,
    )

    rec = Recipient.objects.create(
        subject_id="SCMVR41", date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=date(2025, 1, 1),
    )
    visit = RecipientVisit.objects.create(
        recipient=rec, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8),
    )
    unverified = CMVSerology.objects.create(
        recipient_visit=visit, value=Decimal("3.0"), drawn_date=date(2025, 1, 8),
        entered_by=editor,
    )
    # a fully four-eyes-verified serology — must NOT show in the queue
    CMVSerology.objects.create(
        recipient_visit=visit, value=Decimal("1.0"), drawn_date=date(2025, 1, 9),
        entered_by=editor, verified_by=verifier, verified_at=date(2025, 1, 10),
        is_verified=True,
    )
    DrugLevel.objects.create(
        recipient_visit=visit, analyte="tacrolimus", value=Decimal("8.0"),
        drawn_date=date(2025, 1, 8), entered_by=editor,
    )
    RejectionEpisode.objects.create(
        recipient=rec, onset_date=date(2025, 2, 1), rejection_type="tcmr",
        banff_grade="ia", biopsy_proven=True, entered_by=editor,
    )
    a = Aliquot.objects.create(
        recipient_visit=visit, matrix="plasma", collected_date=date(2025, 1, 8),
        initial_volume_ul=Decimal("1000"),
    )
    run = PipelineRun.objects.create(input_manifest_sha256="a" * 64)
    res = GenotypingResult.objects.create(aliquot=a, pipeline_run=run, assay_type="sanger")
    GenotypeCall.objects.create(
        result=res, locus="gB", allele="gB1", sanger_call="R", entered_by=editor,
    )
    return unverified


@pytest.mark.django_db
def test_worklist_lists_only_unverified_outcome_critical_rows():
    editor = _role_user("dm5", "data_manager")
    reviewer = _role_user("doc5", "reviewing_clinician")
    unverified = _seed_outcome_critical(editor, reviewer)

    resp = _otp_client(reviewer).get(WORKLIST_URL)
    assert resp.status_code == 200
    # exactly the four unverified rows are queued (the verified serology dropped)
    assert resp.context["total"] == 4
    groups = {g["title"]: g["rows"] for g in resp.context["groups"]}
    # every outcome-critical model contributes exactly its one unverified row
    assert all(len(rows) == 1 for rows in groups.values())
    # each row links to its own change page
    change_url = reverse("admin:registry_cmvserology_change", args=[unverified.pk])
    assert any(
        r["url"] == change_url for rows in groups.values() for r in rows
    )
    # the verified serology's change page is NOT linked
    from renova.registry.models import CMVSerology
    verified = CMVSerology.objects.get(is_verified=True)
    verified_url = reverse("admin:registry_cmvserology_change", args=[verified.pk])
    assert not any(
        r["url"] == verified_url for rows in groups.values() for r in rows
    )


@pytest.mark.django_db
def test_worklist_is_permission_gated_to_verifiers():
    from django.test import Client

    reviewer = _role_user("doc5b", "reviewing_clinician")
    analyst = _role_user("ana5b", "data_analyst")

    assert _otp_client(reviewer).get(WORKLIST_URL).status_code == 200
    # the view-only analyst may not verify → the queue is forbidden, not a 200
    assert _otp_client(analyst).get(WORKLIST_URL).status_code == 403
    # anonymous / un-OTP'd is bounced by admin_view (login redirect), never 200
    assert Client().get(WORKLIST_URL).status_code in (301, 302)


@pytest.mark.django_db
def test_index_surfaces_worklist_link_only_for_verifiers():
    reviewer_apps = _app_list(_role_user("doc5c", "reviewing_clinician"))
    review = _section(reviewer_apps, "Review")
    assert review is not None
    assert review["models"][0]["admin_url"] == WORKLIST_URL

    # analyst (view-only) sees sections but no Review worklist entry
    analyst_apps = _app_list(_role_user("ana5c", "data_analyst"))
    assert _section(analyst_apps, "Review") is None


@pytest.mark.django_db
def test_same_user_verify_surfaces_friendly_form_error():
    """Verifier == editor must fail with the model's friendly message THROUGH the
    admin form (a clean() ValidationError), not a bare DB IntegrityError."""
    from datetime import date
    from decimal import Decimal
    from django.contrib import admin as djadmin
    from django.forms.models import model_to_dict
    from django.test import RequestFactory
    from renova.registry.models import CMVSerology, Recipient, RecipientVisit

    reviewer = _role_user("doc5d", "reviewing_clinician")
    rec = Recipient.objects.create(
        subject_id="SCMVR42", date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=date(2025, 1, 1),
    )
    visit = RecipientVisit.objects.create(
        recipient=rec, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8),
    )
    obj = CMVSerology.objects.create(
        recipient_visit=visit, value=Decimal("3.0"), drawn_date=date(2025, 1, 8),
        entered_by=reviewer,
    )

    model_admin = djadmin.site._registry[CMVSerology]
    request = RequestFactory().get("/")
    request.user = reviewer
    Form = model_admin.get_form(request, obj=obj, change=True)

    data = model_to_dict(obj)
    data.update({
        "is_verified": True,
        "verified_by": reviewer.pk,   # SAME user as entered_by → must be rejected
        "verified_at": date(2025, 1, 10),
    })
    form = Form(data, instance=obj)
    assert not form.is_valid()
    assert "verifier must differ" in str(form.errors)


@pytest.mark.django_db
def test_outcome_critical_models_expose_verified_filter():
    from django.contrib import admin as djadmin
    from renova.registry.models import (
        CMVSerology, DrugLevel, GenotypeCall, RejectionEpisode,
    )

    for model in (CMVSerology, DrugLevel, GenotypeCall, RejectionEpisode):
        assert "is_verified" in djadmin.site._registry[model].list_filter


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
