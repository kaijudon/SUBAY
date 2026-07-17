"""Derived read-only rendering + page <title> in the admin (issues #16/#18/#19).

Driven through the real OTP-gated admin test client (same pattern as
test_admin_index.py). A model @property in `readonly_fields` is not a real admin
field, so Django's AdminReadonlyField.contents() used to send it straight through
linebreaksbr() -- None rendered as the literal "None" and a bool as "True"/"False".
The admin now shadows each derived property with an @admin.display wrapper, so
empties become a "-" placeholder and booleans render the Yes/No/unknown icon.
"""
import inspect
import re
from datetime import date
from decimal import Decimal

import pytest
from django.contrib import admin as django_admin
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from subay.registry.models import CMVSerology, Recipient, RecipientVisit


def _otp_client(user):
    """A logged-in, OTP-verified client for `user` (OTPAdminSite needs it)."""
    device = TOTPDevice.objects.create(user=user, name="test", confirmed=True)
    client = Client()
    client.force_login(user)
    session = client.session
    session["otp_device_id"] = device.persistent_id
    session.save()
    return client


@pytest.fixture
def admin_client(db):
    return _otp_client(User.objects.create_superuser("root", "root@x", "pw"))


# --- drift guard: every property-typed readonly/list_display field is routed ----
# through _install_derived_displays (code-review finding #2). Without this test a
# future derived readonly field that nobody remembers to register regresses to the
# literal "None"/"True"/"False" bug (#16/#19) silently. The rule: if a model has a
# name as a `property`, the admin (or inline) that exposes it must SHADOW it with a
# callable on the admin class -- the _derived_display wrapper -- so lookup_field
# picks the admin method over the bare property.

def _admin_field_owners():
    """Yield (label, admin_class, model, fields) for each registered admin and
    each of its inlines. `fields` is the union of readonly_fields + list_display."""
    for model, admin_obj in django_admin.site._registry.items():
        admin_class = type(admin_obj)
        fields = tuple(admin_obj.readonly_fields) + tuple(admin_obj.list_display)
        yield (admin_class.__name__, admin_class, model, fields)
        for inline in getattr(admin_obj, "inlines", ()):
            in_fields = tuple(getattr(inline, "readonly_fields", ())) + tuple(
                getattr(inline, "list_display", ())
            )
            yield (inline.__name__, inline, inline.model, in_fields)


def test_property_typed_readonly_fields_are_routed_through_wrapper():
    """Any model @property named in an admin's readonly_fields/list_display must be
    shadowed by a callable on the admin class, not left as the bare property."""
    offenders = set()
    for label, admin_class, model, fields in _admin_field_owners():
        for name in fields:
            model_attr = inspect.getattr_static(model, name, None)
            if not isinstance(model_attr, property):
                continue  # real field or non-property callable -- not the bug class
            shadow = inspect.getattr_static(admin_class, name, None)
            if not callable(shadow) or isinstance(shadow, property):
                offenders.add(f"{label}.{name}")
    assert not offenders, (
        "Derived @property readonly/list_display fields not routed through "
        "_install_derived_displays (would regress to literal None/True/False): "
        + ", ".join(sorted(offenders))
    )


# --- #16: add-form derived fields -----------------------------------------

def test_recipient_add_form_shows_placeholder_not_none(admin_client):
    """A blank Recipient derives age/risk/summary = None; they must render the
    "-" placeholder, never the literal "None"."""
    html = admin_client.get(reverse("admin:registry_recipient_add")).content.decode()
    assert 'class="readonly">None<' not in html  # #16: no literal "None"
    assert 'class="readonly">-</div>' in html  # placeholder is shown instead


def test_recipient_add_form_boolean_renders_icon_not_false(admin_client):
    """has_donor_serostatus_mismatch is False on a blank Recipient -> the No icon,
    not the literal "False"."""
    html = admin_client.get(reverse("admin:registry_recipient_add")).content.decode()
    assert 'class="readonly">False<' not in html  # #16/#19: no literal "False"
    assert "icon-no.svg" in html  # the boolean No icon is rendered


# --- #19: change-form derived booleans ------------------------------------

@pytest.fixture
def serology(db):
    r = Recipient.objects.create(
        subject_id="SCMVR01", date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=date(2025, 1, 1),
    )
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 15)
    )
    # value >= 2.0 -> is_positive True; igm_value unset -> igm_positive None.
    return CMVSerology.objects.create(
        recipient_visit=v, value=Decimal("3.0"), result_status="reported",
        drawn_date=date(2025, 1, 15),
    )


def test_serology_change_form_true_boolean_renders_yes_icon(admin_client, serology):
    html = admin_client.get(
        reverse("admin:registry_cmvserology_change", args=[serology.pk])
    ).content.decode()
    assert 'class="readonly">True<' not in html  # #19: no literal "True"
    assert "icon-yes.svg" in html  # is_positive True -> Yes icon


def test_serology_change_form_none_boolean_renders_unknown_icon(admin_client, serology):
    """igm_positive is None (not measured) -> the three-state unknown icon, not
    the literal "None"."""
    html = admin_client.get(
        reverse("admin:registry_cmvserology_change", args=[serology.pk])
    ).content.decode()
    assert 'class="readonly">None<' not in html
    assert "icon-unknown.svg" in html


# --- #18: page <title> is never blank -------------------------------------

@pytest.mark.parametrize(
    "url_name",
    ["admin:index", "admin:registry_recipient_changelist", "admin:registry_recipient_add"],
)
def test_admin_pages_have_a_non_blank_title(admin_client, url_name):
    html = admin_client.get(reverse(url_name)).content.decode()
    match = re.search(r"<title>(.*?)</title>", html, re.S)
    assert match is not None
    title = match.group(1).strip()
    assert title != ""  # #18: contrib base.html left this empty site-wide
    assert "SUBAY" in title  # site_title default flows through
