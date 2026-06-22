from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import (
    Aliquot,
    ClosureDay,
    CMVQuantitative,
    CMVSerology,
    ConsumptionEvent,
    Donor,
    DonorVisit,
    DrugLevel,
    Hospitalization,
    MedicationCourse,
    OtherCondition,
    PipelineRun,
    Recipient,
    RecipientVisit,
    RejectionEpisode,
    RenalFunction,
    SequencingAliquot,
    TBNKPanel,
    ThawEvent,
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


class TBNKPanelInline(admin.TabularInline):
    model = TBNKPanel
    fk_name = "recipient_visit"
    extra = 0


class RenalFunctionInline(admin.TabularInline):
    model = RenalFunction
    fk_name = "recipient_visit"
    extra = 0


class DrugLevelInline(admin.TabularInline):
    model = DrugLevel
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


class MedicationCourseInline(admin.TabularInline):
    model = MedicationCourse
    extra = 0


class RejectionEpisodeInline(admin.TabularInline):
    model = RejectionEpisode
    extra = 0


class HospitalizationInline(admin.TabularInline):
    model = Hospitalization
    extra = 0


@admin.register(Recipient)
class RecipientAdmin(SimpleHistoryAdmin):
    list_display = (
        "subject_id", "sex", "kt_date", "age", "risk_stratum", "induction_agent",
        "completion_status", "sequencing_included",
    )
    # derived values are read-only — computed, never editable
    readonly_fields = (
        "age", "risk_stratum", "has_donor_serostatus_mismatch", "cmv_episode_summary",
    )
    inlines = [
        RecipientVisitInline, OtherConditionInline,
        MedicationCourseInline, RejectionEpisodeInline, HospitalizationInline,
    ]


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
    inlines = [
        CMVSerologyInline, CMVQuantitativeInline,
        TBNKPanelInline, RenalFunctionInline, DrugLevelInline,
    ]


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
        "id", "recipient_visit", "donor", "value", "severity_tier", "result_status",
        "drawn_date",
    )


@admin.register(TBNKPanel)
class TBNKPanelAdmin(SimpleHistoryAdmin):
    list_display = (
        "id", "recipient_visit", "donor", "cd3_cd4_count", "cd3_cd8_count",
        "cd4_cd8_ratio", "drawn_date",
    )
    readonly_fields = ("cd4_cd8_ratio",)  # derived, never stored


@admin.register(RenalFunction)
class RenalFunctionAdmin(SimpleHistoryAdmin):
    list_display = (
        "id", "recipient_visit", "donor", "serum_creatinine_mg_dl", "eGFR",
        "result_status", "drawn_date",
    )
    readonly_fields = ("eGFR",)  # derived via CKD-EPI 2021, never stored


@admin.register(DrugLevel)
class DrugLevelAdmin(SimpleHistoryAdmin):
    list_display = (
        "id", "recipient_visit", "donor", "analyte", "value", "result_status", "drawn_date",
    )


@admin.register(MedicationCourse)
class MedicationCourseAdmin(SimpleHistoryAdmin):
    list_display = (
        "id", "recipient", "drug_class", "agent", "dose_amount", "dose_unit", "frequency",
        "course_type", "change_direction", "duration_days",
    )
    readonly_fields = ("duration_days",)  # derived, never stored


@admin.register(RejectionEpisode)
class RejectionEpisodeAdmin(SimpleHistoryAdmin):
    list_display = (
        "id", "recipient", "onset_date", "rejection_type", "banff_grade",
        "biopsy_proven", "resolved_date",
    )


@admin.register(Hospitalization)
class HospitalizationAdmin(SimpleHistoryAdmin):
    list_display = (
        "id", "recipient", "admit_date", "discharge_date", "length_of_stay_days",
        "disposition", "cmv_attributable",
    )
    readonly_fields = ("length_of_stay_days",)  # derived, never stored


# --- Slice 09: biobank ledger (append-only events) ---


class AppendOnlyEventMixin:
    """Append-only audit guarantee (AC2): a recorded thaw/consumption event can be
    ADDED but never changed or deleted, in inline and standalone admin alike — the
    event log is immutable so the ledger cannot be rewritten."""

    def has_change_permission(self, request, obj=None):
        return obj is None  # allow the add form, forbid editing an existing event

    def has_delete_permission(self, request, obj=None):
        return False


class ThawEventInline(AppendOnlyEventMixin, admin.TabularInline):
    model = ThawEvent
    extra = 0


class ConsumptionEventInline(AppendOnlyEventMixin, admin.TabularInline):
    model = ConsumptionEvent
    extra = 0


@admin.register(Aliquot)
class AliquotAdmin(SimpleHistoryAdmin):
    list_display = (
        "id", "recipient_visit", "matrix", "collected_date", "initial_volume_ul",
        "remaining_ul", "thaw_count",
    )
    readonly_fields = ("remaining_ul", "thaw_count")  # derived from the event log
    inlines = [ThawEventInline, ConsumptionEventInline]


@admin.register(ThawEvent)
class ThawEventAdmin(AppendOnlyEventMixin, SimpleHistoryAdmin):
    list_display = ("id", "aliquot", "thawed_date")


@admin.register(ConsumptionEvent)
class ConsumptionEventAdmin(AppendOnlyEventMixin, SimpleHistoryAdmin):
    list_display = ("id", "aliquot", "volume_ul", "consumed_date", "pipeline_run")


@admin.register(SequencingAliquot)
class SequencingAliquotAdmin(SimpleHistoryAdmin):
    list_display = ("id", "aliquot", "transfer_date", "destruction_certificate")


@admin.register(PipelineRun)
class PipelineRunAdmin(SimpleHistoryAdmin):
    list_display = ("id",)
