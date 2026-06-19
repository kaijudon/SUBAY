from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import (
    ClosureDay,
    CMVQuantitative,
    CMVSerology,
    Donor,
    DonorVisit,
    OtherCondition,
    Recipient,
    RecipientVisit,
)
from .sites import RenovaAdminSite  # re-exported; the class is defined in sites.py

__all__ = ["RenovaAdminSite"]


class CMVSerologyInline(admin.TabularInline):
    model = CMVSerology
    fk_name = "recipient_visit"
    extra = 0


class CMVQuantitativeInline(admin.TabularInline):
    model = CMVQuantitative
    fk_name = "recipient_visit"
    extra = 0


class RecipientVisitInline(admin.TabularInline):
    model = RecipientVisit
    extra = 0


class OtherConditionInline(admin.TabularInline):
    model = OtherCondition
    extra = 0


class DonorVisitInline(admin.TabularInline):
    model = DonorVisit
    extra = 0


@admin.register(Recipient)
class RecipientAdmin(SimpleHistoryAdmin):
    list_display = (
        "subject_id", "sex", "kt_date", "age", "risk_stratum", "induction_agent",
        "completion_status", "sequencing_included",
    )
    # derived values are read-only — computed, never editable
    readonly_fields = ("age", "risk_stratum", "has_donor_serostatus_mismatch")
    inlines = [RecipientVisitInline, OtherConditionInline]


@admin.register(RecipientVisit)
class RecipientVisitAdmin(SimpleHistoryAdmin):
    list_display = (
        "id", "recipient", "timepoint_label", "actual_visit_date", "completion_status",
        "nominal_day", "closure_shifted", "closure_reason", "shift_days_from_nominal",
    )
    # scheduling values are computed, never editable
    readonly_fields = (
        "nominal_day", "closure_shifted", "closure_reason", "shift_days_from_nominal",
    )
    inlines = [CMVSerologyInline, CMVQuantitativeInline]


@admin.register(ClosureDay)
class ClosureDayAdmin(SimpleHistoryAdmin):
    list_display = ("date", "reason", "reference", "closes_clinic", "closes_lab")


@admin.register(DonorVisit)
class DonorVisitAdmin(SimpleHistoryAdmin):
    list_display = ("id", "donor", "draw_date")


@admin.register(Donor)
class DonorAdmin(SimpleHistoryAdmin):
    list_display = ("subject_id", "sex", "donor_type", "relation", "baseline_serostatus")
    readonly_fields = ("baseline_serostatus",)  # derived from the single serology
    inlines = [DonorVisitInline]


@admin.register(OtherCondition)
class OtherConditionAdmin(SimpleHistoryAdmin):
    list_display = ("id", "recipient", "condition", "present")


@admin.register(CMVSerology)
class CMVSerologyAdmin(SimpleHistoryAdmin):
    list_display = (
        "id", "recipient_visit", "donor", "value", "is_positive", "result_status", "drawn_date",
    )
    readonly_fields = ("is_positive", "igm_positive")  # derived at the 2.0 AU/mL threshold


@admin.register(CMVQuantitative)
class CMVQuantitativeAdmin(SimpleHistoryAdmin):
    list_display = (
        "id", "recipient_visit", "donor", "value", "result_status", "drawn_date",
    )
