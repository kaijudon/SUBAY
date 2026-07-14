from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from simple_history.admin import SimpleHistoryAdmin

from .models import (
    Aliquot,
    ClosureDay,
    CMVQuantitative,
    CMVSerology,
    ConcordancePair,
    ConsumptionEvent,
    Donor,
    DonorVisit,
    DrugLevel,
    GenotypeCall,
    GenotypingResult,
    Hospitalization,
    MedicationCourse,
    OtherCondition,
    PipelineRun,
    ProtocolDeviation,
    QpcrDetail,
    QpcrProbeReading,
    Recipient,
    RecipientVisit,
    ReferenceAccession,
    ReferenceSet,
    RejectionEpisode,
    ReleaseEvent,
    RenalFunction,
    SangerDetail,
    SequencingAliquot,
    TBNKPanel,
    ThawEvent,
)
from .sites import SubayAdminSite  # re-exported; the class is defined in sites.py

__all__ = ["SubayAdminSite"]


# --- Front-end 1 (issue #2): filters for DERIVED values ---
#
# risk_stratum and closure_shifted are @property (derive-don't-store), so neither
# is a column list_filter can key on. These SimpleListFilters re-express each one
# the way the model derives it — risk in ORM terms, closure via the ClosureDay
# calendar — so the changelist filters without ever storing the derived value.


class RiskStratumListFilter(SimpleListFilter):
    """Filter recipients by CMV risk stratum. Mirrors Recipient.risk_stratum
    (D+/R- = high, any R+ = intermediate, D-/R- = low) as serostatus lookups; a
    stratum is only defined when both serostatuses are recorded."""

    title = "risk stratum"
    parameter_name = "risk_stratum"

    def lookups(self, request, model_admin):
        return [("high", "high (D+/R-)"), ("intermediate", "intermediate (R+)"), ("low", "low (D-/R-)")]

    def queryset(self, request, queryset):
        value = self.value()
        if value == "high":
            return queryset.filter(donor_serostatus="POS", recipient_serostatus="NEG")
        if value == "intermediate":
            # R+ (D+/R+ or D-/R+). The property needs BOTH serostatuses present,
            # so require a recorded donor status too — else the stratum is None.
            return queryset.filter(recipient_serostatus="POS", donor_serostatus__isnull=False)
        if value == "low":
            return queryset.filter(donor_serostatus="NEG", recipient_serostatus="NEG")
        return queryset


class ClosureShiftedListFilter(SimpleListFilter):
    """Filter visits by whether the closure calendar forced a forward shift.
    closure_shifted compares the scheduled day (first day clinic AND lab both
    operate) against nominal — pure Python over ClosureDay, not expressible in
    SQL — so this scans pks. Fine at the study's ~40-recipient scale."""

    title = "closure shifted"
    parameter_name = "closure_shifted"

    def lookups(self, request, model_admin):
        return [("yes", "Yes"), ("no", "No")]

    def queryset(self, request, queryset):
        value = self.value()
        if value not in ("yes", "no"):
            return queryset
        want = value == "yes"
        pks = [v.pk for v in queryset if v.closure_shifted is want]
        return queryset.filter(pk__in=pks)


class _EditorDefaultedAdmin(SimpleHistoryAdmin):
    """Defaults `entered_by` to the acting user on add (no bespoke role code —
    the different-user verification gate is enforced in the model, reusing the
    existing groups), so the admin and shell both attribute entry the same way."""

    def save_model(self, request, obj, form, change):
        if not change and obj.entered_by_id is None:
            obj.entered_by = request.user
        super().save_model(request, obj, form, change)


# Inline derived flags: with `fields` unset, get_fields() appends readonly_fields
# after the editable columns, so each derived @property renders read-only beside
# the value it was computed from — the operator sees what the typed value derived.
class CMVSerologyInline(admin.TabularInline):
    model = CMVSerology
    fk_name = "recipient_visit"
    extra = 0
    readonly_fields = ("is_positive",)


class CMVQuantitativeInline(admin.TabularInline):
    model = CMVQuantitative
    fk_name = "recipient_visit"
    extra = 0
    readonly_fields = ("severity_tier", "release_overdue")


class TBNKPanelInline(admin.TabularInline):
    model = TBNKPanel
    fk_name = "recipient_visit"
    extra = 0
    readonly_fields = ("cd4_cd8_ratio",)


class RenalFunctionInline(admin.TabularInline):
    model = RenalFunction
    fk_name = "recipient_visit"
    extra = 0
    readonly_fields = ("eGFR",)


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
    # subject_id is an opaque string PK; search stays a CharField lookup and never
    # coerces "07" to 7. Declared here so downstream autocomplete_fields can point
    # at Recipient (the prefactor this ticket owns).
    search_fields = ("subject_id",)
    list_filter = ("completion_status", RiskStratumListFilter, "induction_agent")
    # derived values are read-only — computed, never editable
    readonly_fields = (
        "age", "risk_stratum", "has_donor_serostatus_mismatch", "cmv_episode_summary",
    )
    # A dense form, organized: who this is, the clinical facts, the derived
    # read-only values (clearly not hand-entered). Recipient has no verification
    # fields of its own — those live on the outcome-critical lab rows.
    fieldsets = (
        ("Identifying", {"fields": ("subject_id", "date_of_birth", "sex", "kt_date")}),
        ("Clinical", {"fields": (
            "donor", "donor_serostatus", "recipient_serostatus",
            "has_diabetes", "has_hypertension", "dialysis_vintage_months",
            "induction_agent", "completion_status", "sequencing_included",
        )}),
        ("Derived (read-only)", {"fields": (
            "age", "risk_stratum", "has_donor_serostatus_mismatch", "cmv_episode_summary",
        )}),
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
    # Search reaches the recipient's Subject ID (string) — also the prefactor for a
    # downstream autocomplete on the recipient FK.
    search_fields = ("recipient__subject_id",)
    list_filter = ("timepoint_label", "completion_status", ClosureShiftedListFilter)
    date_hierarchy = "actual_visit_date"
    # scheduling values are computed, never editable
    readonly_fields = (
        "nominal_day", "closure_shifted", "closure_reason", "shift_days_from_nominal",
    )
    fieldsets = (
        ("Identifying", {"fields": ("recipient", "timepoint_label")}),
        ("Clinical", {"fields": ("actual_visit_date", "completion_status")}),
        ("Derived scheduling (read-only)", {"fields": (
            "nominal_day", "closure_shifted", "closure_reason", "shift_days_from_nominal",
        )}),
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
    search_fields = ("subject_id",)  # string PK; also the autocomplete prefactor
    readonly_fields = ("baseline_serostatus",)  # derived from the single serology
    # Deliberately thin: one draw, at most one baseline serology, no recipient
    # timeline (no visit spine / closure machinery).
    fieldsets = (
        ("Identifying", {"fields": ("subject_id", "date_of_birth", "sex")}),
        ("Clinical", {"fields": ("donor_type", "relation")}),
        ("Derived (read-only)", {"fields": ("baseline_serostatus",)}),
    )
    inlines = [DonorVisitInline]


@admin.register(OtherCondition)
class OtherConditionAdmin(SimpleHistoryAdmin):
    list_display = ("id", "recipient", "condition", "present")
    autocomplete_fields = ("recipient",)


# Lab rows attach to exactly one of recipient_visit XOR donor; autocomplete both
# so a lab is filed against the right visit/subject without scrolling a dropdown.
_LAB_SUBJECT_FKS = ("recipient_visit", "donor")


@admin.register(CMVSerology)
class CMVSerologyAdmin(_EditorDefaultedAdmin):
    list_display = (
        "id", "recipient_visit", "donor", "value", "is_positive", "result_status",
        "drawn_date", "verified_by", "is_verified",
    )
    autocomplete_fields = _LAB_SUBJECT_FKS
    list_filter = ("is_verified", "result_status")
    readonly_fields = ("is_positive", "igm_positive")  # derived at the 2.0 AU/mL threshold


@admin.register(CMVQuantitative)
class CMVQuantitativeAdmin(SimpleHistoryAdmin):
    list_display = (
        "id", "recipient_visit", "donor", "value", "severity_tier", "result_status",
        "drawn_date", "release_overdue",
    )
    autocomplete_fields = _LAB_SUBJECT_FKS
    # searchable so the Safety FKs (ReleaseEvent/ProtocolDeviation.quantitative)
    # can autocomplete against it.
    search_fields = ("recipient_visit__recipient__subject_id", "donor__subject_id")
    list_filter = ("result_status",)
    readonly_fields = ("release_overdue",)  # derived Safety-Monitor flag, never stored


@admin.register(TBNKPanel)
class TBNKPanelAdmin(SimpleHistoryAdmin):
    list_display = (
        "id", "recipient_visit", "donor", "cd3_cd4_count", "cd3_cd8_count",
        "cd4_cd8_ratio", "drawn_date",
    )
    autocomplete_fields = _LAB_SUBJECT_FKS
    readonly_fields = ("cd4_cd8_ratio",)  # derived, never stored


@admin.register(RenalFunction)
class RenalFunctionAdmin(SimpleHistoryAdmin):
    list_display = (
        "id", "recipient_visit", "donor", "serum_creatinine_mg_dl", "eGFR",
        "result_status", "drawn_date",
    )
    autocomplete_fields = _LAB_SUBJECT_FKS
    readonly_fields = ("eGFR",)  # derived via CKD-EPI 2021, never stored


@admin.register(DrugLevel)
class DrugLevelAdmin(_EditorDefaultedAdmin):
    list_display = (
        "id", "recipient_visit", "donor", "analyte", "value", "result_status",
        "drawn_date", "verified_by", "is_verified",
    )
    autocomplete_fields = _LAB_SUBJECT_FKS
    list_filter = ("analyte", "is_verified")


@admin.register(MedicationCourse)
class MedicationCourseAdmin(SimpleHistoryAdmin):
    list_display = (
        "id", "recipient", "drug_class", "agent", "dose_amount", "dose_unit", "frequency",
        "course_type", "change_direction", "duration_days",
    )
    autocomplete_fields = ("recipient",)
    readonly_fields = ("duration_days",)  # derived, never stored


@admin.register(RejectionEpisode)
class RejectionEpisodeAdmin(_EditorDefaultedAdmin):
    list_display = (
        "id", "recipient", "onset_date", "rejection_type", "banff_grade",
        "biopsy_proven", "resolved_date", "verified_by", "is_verified",
    )
    autocomplete_fields = ("recipient",)
    list_filter = ("is_verified",)


@admin.register(Hospitalization)
class HospitalizationAdmin(SimpleHistoryAdmin):
    list_display = (
        "id", "recipient", "admit_date", "discharge_date", "length_of_stay_days",
        "disposition", "cmv_attributable",
    )
    autocomplete_fields = ("recipient",)
    readonly_fields = ("length_of_stay_days",)  # derived, never stored


# --- Slice 09: biobank ledger (append-only events) ---


class AppendOnlyEventMixin:
    """Append-only audit guarantee (AC2): a recorded thaw/consumption event can be
    ADDED but never changed or deleted, in inline and standalone admin alike — the
    event log is immutable so the ledger cannot be rewritten."""

    def has_change_permission(self, request, obj=None):
        # Forbid editing an EXISTING event (append-only). For the module-level
        # check (obj is None) defer to the user's real Django permission, so role
        # scoping still applies — the mixin must not hand every staff user a
        # phantom change right on the ledger models.
        if obj is not None:
            return False
        return super().has_change_permission(request, obj)

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
    autocomplete_fields = ("recipient_visit",)
    list_filter = ("matrix",)
    # searchable by subject so the event/genotyping FKs can autocomplete against it
    search_fields = ("recipient_visit__recipient__subject_id",)
    readonly_fields = ("remaining_ul", "thaw_count")  # derived from the event log
    inlines = [ThawEventInline, ConsumptionEventInline]


@admin.register(ThawEvent)
class ThawEventAdmin(AppendOnlyEventMixin, SimpleHistoryAdmin):
    list_display = ("id", "aliquot", "thawed_date")
    autocomplete_fields = ("aliquot",)


@admin.register(ConsumptionEvent)
class ConsumptionEventAdmin(AppendOnlyEventMixin, SimpleHistoryAdmin):
    list_display = ("id", "aliquot", "volume_ul", "consumed_date", "pipeline_run")
    autocomplete_fields = ("aliquot", "pipeline_run")


@admin.register(SequencingAliquot)
class SequencingAliquotAdmin(SimpleHistoryAdmin):
    list_display = ("id", "aliquot", "transfer_date", "destruction_certificate")
    autocomplete_fields = ("aliquot",)


@admin.register(PipelineRun)
class PipelineRunAdmin(SimpleHistoryAdmin):
    list_display = ("id", "input_manifest_sha256", "reference_set", "started_at", "completed_at")
    search_fields = ("input_manifest_sha256",)  # autocomplete target for *.pipeline_run


# --- Slice 10: genotyping ingest (provenance; second-reviewer lock) ---


class GenotypeCallInline(admin.TabularInline):
    model = GenotypeCall
    extra = 0


class SangerDetailInline(admin.TabularInline):
    model = SangerDetail
    extra = 0


class QpcrDetailInline(admin.TabularInline):
    model = QpcrDetail
    extra = 0


class QpcrProbeReadingInline(admin.TabularInline):
    model = QpcrProbeReading
    extra = 0


class ReferenceAccessionInline(admin.TabularInline):
    model = ReferenceAccession
    extra = 0


@admin.register(GenotypingResult)
class GenotypingResultAdmin(SimpleHistoryAdmin):
    list_display = ("id", "aliquot", "pipeline_run", "assay_type", "subject", "sample_date")
    autocomplete_fields = ("aliquot", "pipeline_run")
    # searchable by subject so the detail/call FKs (*.result) can autocomplete
    search_fields = ("aliquot__recipient_visit__recipient__subject_id",)
    readonly_fields = ("subject", "sample_date", "qpcr_rollup")  # derived through the tube
    inlines = [GenotypeCallInline, SangerDetailInline, QpcrDetailInline]


@admin.register(GenotypeCall)
class GenotypeCallAdmin(_EditorDefaultedAdmin):
    list_display = (
        "id", "result", "locus", "allele", "sanger_call", "entered_by",
        "verified_by", "is_verified",
    )
    autocomplete_fields = ("result",)
    list_filter = ("is_verified",)


@admin.register(QpcrProbeReading)
class QpcrProbeReadingAdmin(_EditorDefaultedAdmin):
    list_display = ("id", "qpcr_detail", "probe", "call", "entered_by", "reviewed_by")
    autocomplete_fields = ("qpcr_detail",)


@admin.register(QpcrDetail)
class QpcrDetailAdmin(SimpleHistoryAdmin):
    list_display = ("id", "result", "rollup")
    autocomplete_fields = ("result",)
    search_fields = ("result__aliquot__recipient_visit__recipient__subject_id",)  # autocomplete target
    readonly_fields = ("rollup",)  # derived from the probe readings
    inlines = [QpcrProbeReadingInline]


@admin.register(SangerDetail)
class SangerDetailAdmin(SimpleHistoryAdmin):
    list_display = ("id", "result", "raw_ab1_sha256", "edited_by")
    autocomplete_fields = ("result",)


@admin.register(ReferenceSet)
class ReferenceSetAdmin(SimpleHistoryAdmin):
    list_display = ("id", "name", "content_sha256", "pinned_at")
    inlines = [ReferenceAccessionInline]


# --- Slice 11: source attribution & genotype concordance (Obj 5) ---


@admin.register(ConcordancePair)
class ConcordancePairAdmin(SimpleHistoryAdmin):
    list_display = (
        "id", "recipient", "recipient_result", "comparator_result",
        "concordance_call", "superinfection_status",
    )
    autocomplete_fields = ("recipient", "recipient_result", "comparator_result")
    # the grader's outputs are computed, never editable
    readonly_fields = ("suggested_concordance_call", "co_resolved_count", "comparator_subject")


# --- Slice 14: safety release-timeliness surface (Safety Monitor) ---


@admin.register(ReleaseEvent)
class ReleaseEventAdmin(SimpleHistoryAdmin):
    list_display = ("id", "quantitative", "released_date", "recipient")
    autocomplete_fields = ("quantitative",)
    readonly_fields = ("recipient",)  # derived through the tube, never stored


@admin.register(ProtocolDeviation)
class ProtocolDeviationAdmin(SimpleHistoryAdmin):
    list_display = (
        "id", "quantitative", "deviation_type", "caused_harm",
        "is_research_related_sae", "recorded_date",
    )
    autocomplete_fields = ("quantitative",)
    readonly_fields = ("recipient",)  # derived through the tube, never stored
