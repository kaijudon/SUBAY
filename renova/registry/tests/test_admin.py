from datetime import date, timedelta

import pytest
from django.contrib import admin
from django.test import RequestFactory
from django_otp.admin import OTPAdminSite

from renova.registry.admin import (
    ClosureShiftedListFilter,
    RenovaAdminSite,
    RiskStratumListFilter,
)
from renova.registry.models import (
    Aliquot,
    ClosureDay,
    CMVQuantitative,
    CMVSerology,
    ConcordancePair,
    ConsumptionEvent,
    Donor,
    DrugLevel,
    Hospitalization,
    MedicationCourse,
    OtherCondition,
    ProtocolDeviation,
    Recipient,
    RecipientVisit,
    RejectionEpisode,
    ReleaseEvent,
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


# --- Slice 14: safety release-timeliness admin ---


def test_slice14_models_are_registered():
    assert ReleaseEvent in admin.site._registry
    assert ProtocolDeviation in admin.site._registry


def test_quantitative_admin_shows_release_overdue_readonly():
    ma = admin.site._registry[CMVQuantitative]
    assert "release_overdue" in ma.readonly_fields
    assert "release_overdue" in ma.list_display


class _User:
    def has_perm(self, perm):
        return True


class _Req:
    method = "GET"
    user = _User()


def _req():
    return _Req()


# --- Front-end 1 (issue #2): core subject/visit spine ergonomics ----------
#
# Seam: the admin config plus its query hooks against the real stack. Search is
# exercised through ModelAdmin.get_search_results and the custom list-filter
# querysets (the derived risk/closure filters can't be plain field lookups),
# so we prove behavior, not just declarations, without an OTP-verified client.

_RF = RequestFactory()


def _filter(filter_cls, model_admin, model, **params):
    """Build a SimpleListFilter the way the changelist does — from a request —
    so Django 5.x list-valued params parse correctly."""
    request = _RF.get("/", params)
    used = {k: request.GET.getlist(k) for k in request.GET}
    return filter_cls(request, used, model, model_admin)


@pytest.fixture
def recipients(db):
    """One high-risk (D+/R-) and one low-risk (D-/R-) recipient."""
    high = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=date(2025, 1, 1), donor_serostatus="POS", recipient_serostatus="NEG",
        induction_agent="atg", completion_status="enrolled",
    )
    low = Recipient.objects.create(
        subject_id="SCMVR12", date_of_birth=date(1975, 1, 1), sex="F",
        kt_date=date(2025, 2, 1), donor_serostatus="NEG", recipient_serostatus="NEG",
        induction_agent="basiliximab", completion_status="completed",
    )
    return high, low


def test_recipient_searchable_by_subject_id_string(recipients):
    """AC: search by Subject ID as a string; '07' never coerced to int 7."""
    ma = admin.site._registry[Recipient]
    assert "subject_id" in ma.search_fields
    qs, _distinct = ma.get_search_results(_RF.get("/"), Recipient.objects.all(), "07")
    ids = list(qs.values_list("subject_id", flat=True))  # forces the query
    assert ids == ["SCMVR07"]  # matched the string, did not blow up on int()


def test_recipient_changelist_has_the_three_filters(recipients):
    ma = admin.site._registry[Recipient]
    assert "completion_status" in ma.list_filter
    assert "induction_agent" in ma.list_filter
    assert RiskStratumListFilter in ma.list_filter


def test_risk_stratum_filter_queryset_mirrors_the_derived_property(recipients):
    high, low = recipients
    ma = admin.site._registry[Recipient]
    hi = _filter(RiskStratumListFilter, ma, Recipient, risk_stratum="high")
    got = list(hi.queryset(_RF.get("/"), Recipient.objects.all()))
    assert got == [high]
    # the filter agrees with the model's own derivation
    assert high.risk_stratum == "high" and low.risk_stratum == "low"
    lo = _filter(RiskStratumListFilter, ma, Recipient, risk_stratum="low")
    assert list(lo.queryset(_RF.get("/"), Recipient.objects.all())) == [low]


# --- Front-end 2 (issue #4): lab & clinical-event ergonomics -------------


def test_lab_admins_autocomplete_visit_and_subject_fks():
    for model in (CMVSerology, CMVQuantitative, TBNKPanel, RenalFunction, DrugLevel):
        ma = admin.site._registry[model]
        assert "recipient_visit" in ma.autocomplete_fields
        assert "donor" in ma.autocomplete_fields


def test_clinical_event_admins_autocomplete_recipient():
    for model in (OtherCondition, MedicationCourse, RejectionEpisode, Hospitalization):
        assert "recipient" in admin.site._registry[model].autocomplete_fields


def test_biobank_and_genotyping_autocomplete_and_target_search_fields():
    from renova.registry.models import GenotypeCall, GenotypingResult, PipelineRun

    assert "aliquot" in admin.site._registry[ThawEvent].autocomplete_fields
    assert "aliquot" in admin.site._registry[ConsumptionEvent].autocomplete_fields
    gr = admin.site._registry[GenotypingResult]
    assert "aliquot" in gr.autocomplete_fields
    assert "result" in admin.site._registry[GenotypeCall].autocomplete_fields
    # every autocomplete target must declare search_fields or Django raises E040
    assert admin.site._registry[Aliquot].search_fields
    assert admin.site._registry[GenotypingResult].search_fields
    assert admin.site._registry[PipelineRun].search_fields
    assert admin.site._registry[CMVQuantitative].search_fields


def test_lab_changelist_filters_matrix_analyte_verified():
    assert "matrix" in admin.site._registry[Aliquot].list_filter
    dl = admin.site._registry[DrugLevel].list_filter
    assert "analyte" in dl and "is_verified" in dl
    assert "is_verified" in admin.site._registry[CMVSerology].list_filter


def test_inline_lab_rows_show_derived_flags_readonly():
    visit_ma = admin.site._registry[RecipientVisit]
    inline_ro = {i.model: i.readonly_fields for i in visit_ma.inlines}
    assert "is_positive" in inline_ro[CMVSerology]
    assert "severity_tier" in inline_ro[CMVQuantitative]
    assert "release_overdue" in inline_ro[CMVQuantitative]
    assert "eGFR" in inline_ro[RenalFunction]


def test_risk_stratum_intermediate_excludes_undefined(db):
    """R+ is intermediate only with BOTH serostatuses recorded — a null donor
    status leaves the stratum undefined (property returns None), so the filter
    must not sweep it in."""
    inter = Recipient.objects.create(
        subject_id="SCMVR20", date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=date(2025, 1, 1), donor_serostatus="NEG", recipient_serostatus="POS",
    )
    undefined = Recipient.objects.create(
        subject_id="SCMVR21", date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=date(2025, 1, 1), donor_serostatus=None, recipient_serostatus="POS",
    )
    ma = admin.site._registry[Recipient]
    im = _filter(RiskStratumListFilter, ma, Recipient, risk_stratum="intermediate")
    got = list(im.queryset(_RF.get("/"), Recipient.objects.all()))
    assert got == [inter]
    assert inter.risk_stratum == "intermediate" and undefined.risk_stratum is None


def test_recipient_fieldsets_group_derived_readonly(recipients):
    ma = admin.site._registry[Recipient]
    assert ma.fieldsets  # dense form is organized, not a flat field list
    grouped = {f for _label, opts in ma.fieldsets for f in opts["fields"]}
    for derived in ("age", "risk_stratum"):
        assert derived in grouped
        assert derived in ma.readonly_fields


def test_donor_searchable_and_thin(recipients):
    ma = admin.site._registry[Donor]
    assert "subject_id" in ma.search_fields
    # thin: no recipient-timeline machinery bolted on
    assert RecipientVisit not in [i.model for i in ma.inlines]
    assert ma.fieldsets


def test_visit_search_fields_reach_subject_for_autocomplete(recipients):
    """Prefactor: downstream autocomplete_fields=['recipient'] needs this."""
    ma = admin.site._registry[RecipientVisit]
    assert "recipient__subject_id" in ma.search_fields


def test_visit_changelist_filters_and_date_hierarchy(recipients):
    ma = admin.site._registry[RecipientVisit]
    assert "timepoint_label" in ma.list_filter
    assert "completion_status" in ma.list_filter
    assert ClosureShiftedListFilter in ma.list_filter
    assert ma.date_hierarchy == "actual_visit_date"


def test_closure_shifted_filter_queryset(recipients):
    high, _low = recipients
    # day_7 nominal for SCMVR07 = 2025-01-08; close it so the visit shifts.
    ClosureDay.objects.create(date=date(2025, 1, 8), reason="annexed_holiday")
    shifted = RecipientVisit.objects.create(
        recipient=high, timepoint_label="day_7",
        actual_visit_date=date(2025, 1, 9),
    )
    plain = RecipientVisit.objects.create(
        recipient=high, timepoint_label="day_30",
        actual_visit_date=high.kt_date + timedelta(days=30),
    )
    ma = admin.site._registry[RecipientVisit]
    yes = _filter(ClosureShiftedListFilter, ma, RecipientVisit, closure_shifted="yes")
    assert list(yes.queryset(_RF.get("/"), RecipientVisit.objects.all())) == [shifted]
    no = _filter(ClosureShiftedListFilter, ma, RecipientVisit, closure_shifted="no")
    assert list(no.queryset(_RF.get("/"), RecipientVisit.objects.all())) == [plain]
