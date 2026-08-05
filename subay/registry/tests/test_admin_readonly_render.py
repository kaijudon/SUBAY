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

from subay.registry.models import CMVSerology, Donor, Recipient, RecipientVisit


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


def test_recipient_add_form_mismatch_reads_not_comparable_not_false(admin_client):
    """A blank Recipient has no donor to compare against, so the flag says so.

    This asserted the boolean No icon until slice 17 ticket 02. What #16/#19
    established, that a derived value never renders as the literal "False", is
    unchanged and still asserted below; only the rendering it was pinned to
    moved. The icon stopped fitting for two reasons. Its polarity is inverted
    here, since "no mismatch" is the healthy state yet draws the red cross, so a
    clean cohort reads as a column of alarms. And the property now has a third
    answer meaning "these were never compared", which the grey unknown icon
    would report as a missing value rather than the deliberate statement it is.
    """
    html = admin_client.get(reverse("admin:registry_recipient_add")).content.decode()
    assert 'class="readonly">False<' not in html  # #16/#19: no literal "False"
    assert "not comparable" in html
    assert "icon-no.svg" not in html  # no red cross on a record with nothing wrong


# --- #19: change-form derived values (were booleans until slice 17) -------

@pytest.fixture
def serology(db):
    r = Recipient.objects.create(
        subject_id="SCMVR01", date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=date(2025, 1, 1),
    )
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 15)
    )
    # Drawn before the advisory, so 3.0 AU/mL is reactive on the first-generation
    # cutoff; igm_value unset, so igm_interpretation is None (not measured).
    return CMVSerology.objects.create(
        recipient_visit=v, value=Decimal("3.0"), result_status="reported",
        drawn_date=date(2025, 1, 15),
    )


def test_serology_change_form_renders_a_measured_channel_in_words(admin_client, serology):
    """These two tests asserted the Yes/No and unknown ICONS until slice 17
    ticket 03, when the surfaced value became a three-state interpretation.

    An icon carries two states plus a gap; the reading carries three clinical
    answers plus "not measured". What #19 established is untouched and still
    asserted: a derived value never reaches the page as the literal "True",
    "False" or "None". Only the rendering it was pinned to moved.

    The fixture draws on 2025-01-15, before the 2026-06-03 advisory, so 3.0 AU/mL
    is read against the first-generation single cutoff and is reactive.
    """
    html = admin_client.get(
        reverse("admin:registry_cmvserology_change", args=[serology.pk])
    ).content.decode()
    assert 'class="readonly">True<' not in html  # #19: no literal "True"
    assert "Reactive" in html


def test_serology_change_form_unmeasured_channel_shows_the_placeholder(admin_client, serology):
    """The fixture leaves igm_status at its 'missing' default, so the IgM channel
    has no observation. That must render as the "-" placeholder, never "None"."""
    html = admin_client.get(
        reverse("admin:registry_cmvserology_change", args=[serology.pk])
    ).content.decode()
    assert 'class="readonly">None<' not in html
    assert 'class="readonly">-</div>' in html


# --- slice 17 ticket 02: the mismatch flag's three answers on the change form


@pytest.mark.parametrize(
    "recorded,donor_value,expected",
    [
        ("POS", "0.50", "MISMATCH"),       # compared, and they clash
        ("POS", "1.50", "agree"),          # compared, and they agree
        ("POS", "1.00", "not comparable"), # equivocal donor result
    ],
)
def test_recipient_change_form_states_the_mismatch_verdict_in_words(
    db, admin_client, recorded, donor_value, expected
):
    """Words rather than a colour, because the colour would be backwards.

    A green tick would mean "yes, mismatch" - the problem state - and the red
    cross would mark the healthy record. The three answers also cannot survive a
    two-colour icon: "we could not compare these" is a statement, not a gap.
    """
    d = Donor.objects.create(
        subject_id="DCMVD01", date_of_birth=date(1975, 1, 1), sex="F"
    )
    CMVSerology.objects.create(
        donor=d, value=Decimal(donor_value), drawn_date=date(2026, 7, 1)
    )
    r = Recipient.objects.create(
        subject_id="SCMVR02", date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=date(2026, 8, 1), donor=d, donor_serostatus=recorded,
    )
    html = admin_client.get(
        reverse("admin:registry_recipient_change", args=[r.pk])
    ).content.decode()
    assert expected in html
    assert 'class="readonly">None<' not in html
    assert 'class="readonly">False<' not in html


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
