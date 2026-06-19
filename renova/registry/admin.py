from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import CMVSerology, Donor, OtherCondition, Recipient, RecipientVisit
from .sites import RenovaAdminSite  # re-exported; the class is defined in sites.py

__all__ = ["RenovaAdminSite"]


class CMVSerologyInline(admin.TabularInline):
    model = CMVSerology
    fk_name = "recipient_visit"
    extra = 0


class RecipientVisitInline(admin.TabularInline):
    model = RecipientVisit
    extra = 0


class OtherConditionInline(admin.TabularInline):
    model = OtherCondition
    extra = 0


@admin.register(Recipient)
class RecipientAdmin(SimpleHistoryAdmin):
    list_display = ("subject_id", "sex", "kt_date", "age", "risk_stratum", "induction_agent")
    # derived values are read-only — computed, never editable
    readonly_fields = ("age", "risk_stratum", "has_donor_serostatus_mismatch")
    inlines = [RecipientVisitInline, OtherConditionInline]


@admin.register(RecipientVisit)
class RecipientVisitAdmin(SimpleHistoryAdmin):
    list_display = ("id", "recipient", "visit_date")
    inlines = [CMVSerologyInline]


@admin.register(Donor)
class DonorAdmin(SimpleHistoryAdmin):
    list_display = ("subject_id", "sex", "donor_type", "relation", "baseline_serostatus")
    readonly_fields = ("baseline_serostatus",)  # derived from the single serology


@admin.register(OtherCondition)
class OtherConditionAdmin(SimpleHistoryAdmin):
    list_display = ("id", "recipient", "condition", "present")


@admin.register(CMVSerology)
class CMVSerologyAdmin(SimpleHistoryAdmin):
    list_display = ("id", "recipient_visit", "donor", "value", "is_positive", "drawn_date")
    readonly_fields = ("is_positive",)  # derived at the 2.0 AU/mL threshold
