import pytest
from django.contrib import admin
from django_otp.admin import OTPAdminSite

from renova.registry.admin import RenovaAdminSite
from renova.registry.models import (
    Aliquot,
    CMVQuantitative,
    CMVSerology,
    ConcordancePair,
    ConsumptionEvent,
    DrugLevel,
    Hospitalization,
    MedicationCourse,
    OtherCondition,
    Recipient,
    RecipientVisit,
    RejectionEpisode,
    RenalFunction,
    SequencingAliquot,
    TBNKPanel,
    ThawEvent,
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


# --- Slice 06: TBNK / renal / drug-level panels as visit inlines ---


def test_visit_admin_has_slice06_lab_inlines():
    ma = admin.site._registry[RecipientVisit]
    inline_models = [i.model for i in ma.inlines]
    assert TBNKPanel in inline_models
    assert RenalFunction in inline_models
    assert DrugLevel in inline_models


def test_slice06_models_are_registered():
    assert TBNKPanel in admin.site._registry
    assert RenalFunction in admin.site._registry
    assert DrugLevel in admin.site._registry


def test_tbnk_admin_has_ratio_readonly():
    ma = admin.site._registry[TBNKPanel]
    assert "cd4_cd8_ratio" in ma.readonly_fields


def test_renal_admin_has_egfr_readonly():
    ma = admin.site._registry[RenalFunction]
    assert "eGFR" in ma.readonly_fields


# --- Slice 07: episode derivation surfaced in admin ---


def test_quantitative_admin_shows_severity_tier():
    ma = admin.site._registry[CMVQuantitative]
    assert "severity_tier" in ma.list_display


def test_recipient_admin_has_episode_summary_readonly():
    ma = admin.site._registry[Recipient]
    assert "cmv_episode_summary" in ma.readonly_fields


# --- Slice 08: clinical events as recipient inlines ---


def test_recipient_admin_has_slice08_inlines():
    ma = admin.site._registry[Recipient]
    inline_models = [i.model for i in ma.inlines]
    assert MedicationCourse in inline_models
    assert RejectionEpisode in inline_models
    assert Hospitalization in inline_models


def test_slice08_models_are_registered():
    assert MedicationCourse in admin.site._registry
    assert RejectionEpisode in admin.site._registry
    assert Hospitalization in admin.site._registry


def test_medication_admin_has_duration_readonly():
    ma = admin.site._registry[MedicationCourse]
    assert "duration_days" in ma.readonly_fields


def test_hospitalization_admin_has_los_readonly():
    ma = admin.site._registry[Hospitalization]
    assert "length_of_stay_days" in ma.readonly_fields


# --- Slice 09: biobank ledger admin ---


def test_slice09_models_are_registered():
    assert Aliquot in admin.site._registry
    assert ThawEvent in admin.site._registry
    assert ConsumptionEvent in admin.site._registry
    assert SequencingAliquot in admin.site._registry


def test_aliquot_admin_has_event_inlines_and_derived_readonly():
    ma = admin.site._registry[Aliquot]
    inline_models = [i.model for i in ma.inlines]
    assert ThawEvent in inline_models
    assert ConsumptionEvent in inline_models
    assert "remaining_ul" in ma.readonly_fields
    assert "thaw_count" in ma.readonly_fields


@pytest.mark.parametrize("model", [ThawEvent, ConsumptionEvent])
def test_event_admin_is_append_only(model):
    """AC2: a recorded thaw/consumption offers no edit or delete — only add."""
    ma = admin.site._registry[model]
    obj = object()  # a stand-in 'existing' object
    assert ma.has_change_permission(_req(), obj) is False
    assert ma.has_delete_permission(_req(), obj) is False
    # Adding is still allowed (append-only, not read-only): the mixin does not
    # override has_add_permission, so a permitted user may record a new event.
    assert ma.has_add_permission(_req()) is True


# --- Slice 11: concordance pair admin ---


def test_concordance_pair_is_registered():
    assert ConcordancePair in admin.site._registry


def test_concordance_pair_admin_has_derived_readonly():
    ma = admin.site._registry[ConcordancePair]
    assert "suggested_concordance_call" in ma.readonly_fields
    assert "co_resolved_count" in ma.readonly_fields


class _User:
    def has_perm(self, perm):
        return True


class _Req:
    method = "GET"
    user = _User()


def _req():
    return _Req()
