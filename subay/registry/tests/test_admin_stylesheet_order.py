"""The reskin has to be the last stylesheet on every admin screen.

Per-page admin templates add their own stylesheets inside `{% block extrastyle %}`
via `{{ block.super }}` - change_form.html pulls in forms.css, change_list.html
pulls in changelists.css. A child block wraps the parent's, so anything
base_site.html puts in extrastyle is emitted BEFORE those and loses every
specificity tie against them.

That is not a hypothetical. With subay.css in extrastyle, every change form
rendered Django's stock near-black fieldset headings while the dashboard
rendered the reskin's light ones, because forms.css's `fieldset .fieldset-heading`
and the reskin's `.module h2` are both (0,1,1) and the later one won.

base_site.html loads the reskin in `{% block extrahead %}` instead, which
base.html emits after extrastyle. responsive.css still comes last, which is
intended: its rules live inside width media queries and should keep overriding
at narrow viewports.
"""
import re

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from subay.registry.models import Recipient

STYLESHEET = re.compile(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"')


def _otp_client(user):
    device = TOTPDevice.objects.create(user=user, name="test", confirmed=True)
    client = Client()
    client.force_login(user)
    session = client.session
    session["otp_device_id"] = device.persistent_id
    session.save()
    return client


def _sheets(client, url):
    body = client.get(url).content.decode()
    return [href.split("/static/")[-1] for href in STYLESHEET.findall(body)]


@pytest.fixture
def admin_client_otp(db):
    return _otp_client(User.objects.create_superuser("sheets", "sheets@x", "pw"))


@pytest.fixture
def recipient(db):
    import datetime

    return Recipient.objects.create(
        subject_id="SCMVR31",
        kt_date=datetime.date(2026, 1, 5),
        date_of_birth=datetime.date(1980, 6, 1),
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url_name,args",
    [
        ("admin:index", ()),
        ("admin:registry_recipient_changelist", ()),
        ("admin:registry_recipient_add", ()),
    ],
)
def test_reskin_is_loaded_after_every_stock_admin_stylesheet(
    admin_client_otp, url_name, args
):
    sheets = _sheets(admin_client_otp, reverse(url_name, args=args))
    assert "admin/css/subay.css" in sheets, sheets
    reskin = sheets.index("admin/css/subay.css")
    stock = [
        i
        for i, s in enumerate(sheets)
        # responsive.css is deliberately allowed to come last: its rules are
        # inside width media queries and should win at narrow viewports.
        if s.startswith("admin/css/") and s != "admin/css/subay.css"
        and not s.startswith("admin/css/responsive")
    ]
    assert reskin > max(stock), f"reskin at {reskin}, stock sheets at {stock}: {sheets}"


@pytest.mark.django_db
def test_change_form_loads_the_reskin_after_forms_css(admin_client_otp, recipient):
    """The specific pairing that was broken: forms.css against the reskin on a
    change form, which is the screen coordinators spend their day in."""
    sheets = _sheets(
        admin_client_otp,
        reverse("admin:registry_recipient_change", args=(recipient.pk,)),
    )
    assert "admin/css/forms.css" in sheets, sheets
    assert sheets.index("admin/css/subay.css") > sheets.index("admin/css/forms.css")
