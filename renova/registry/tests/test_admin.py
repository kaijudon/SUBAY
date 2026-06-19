from django.contrib import admin
from django_otp.admin import OTPAdminSite

from renova.registry.admin import RenovaAdminSite
from renova.registry.models import (
    CMVQuantitative,
    CMVSerology,
    OtherCondition,
    Recipient,
    RecipientVisit,
)


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


def test_visit_admin_has_quantitative_inline():
    ma = admin.site._registry[RecipientVisit]
    assert CMVQuantitative in [i.model for i in ma.inlines]


def test_quantitative_is_registered():
    assert CMVQuantitative in admin.site._registry


def test_serology_admin_has_igm_positive_readonly():
    ma = admin.site._registry[CMVSerology]
    assert "is_positive" in ma.readonly_fields
    assert "igm_positive" in ma.readonly_fields


def test_recipient_admin_has_other_condition_inline_and_mismatch_readonly():
    ma = admin.site._registry[Recipient]
    assert OtherCondition in [i.model for i in ma.inlines]
    assert "has_donor_serostatus_mismatch" in ma.readonly_fields


def test_other_condition_is_registered():
    assert OtherCondition in admin.site._registry
