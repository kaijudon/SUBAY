from django.contrib import admin
from django_otp.admin import OTPAdminSite

from renova.registry.admin import RenovaAdminSite
from renova.registry.models import CMVSerology, Recipient, RecipientVisit


def test_admin_site_is_otp_enforced_and_branded():
    assert isinstance(admin.site, OTPAdminSite)
    assert isinstance(admin.site, RenovaAdminSite)
    assert admin.site.site_header == "RENOVA"


def test_recipient_admin_has_visit_inline_and_readonly_derived():
    ma = admin.site._registry[Recipient]
    assert RecipientVisit in [i.model for i in ma.inlines]
    assert "age" in ma.readonly_fields
    assert "risk_stratum" in ma.readonly_fields


def test_visit_admin_has_serology_inline():
    ma = admin.site._registry[RecipientVisit]
    assert CMVSerology in [i.model for i in ma.inlines]
