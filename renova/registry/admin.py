from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import CMVSerology, Donor, Recipient, RecipientVisit
from .sites import RenovaAdminSite  # re-exported; the class is defined in sites.py

__all__ = ["RenovaAdminSite"]


class CMVSerologyInline(admin.TabularInline):
    model = CMVSerology
    fk_name = "recipient_visit"
    extra = 0


class RecipientVisitInline(admin.TabularInline):
    model = RecipientVisit
    extra = 0


@admin.register(Recipient)
class RecipientAdmin(SimpleHistoryAdmin):
    list_display = ("subject_id", "sex", "kt_date", "age", "risk_stratum")
    readonly_fields = ("age", "risk_stratum")  # derived, not editable
    inlines = [RecipientVisitInline]


@admin.register(RecipientVisit)
class RecipientVisitAdmin(SimpleHistoryAdmin):
    list_display = ("id", "recipient", "visit_date")
    inlines = [CMVSerologyInline]


@admin.register(Donor)
class DonorAdmin(SimpleHistoryAdmin):
    list_display = ("subject_id", "sex")


@admin.register(CMVSerology)
class CMVSerologyAdmin(SimpleHistoryAdmin):
    list_display = ("id", "recipient_visit", "donor", "value", "is_positive", "drawn_date")
    readonly_fields = ("is_positive",)  # derived at the 2.0 AU/mL threshold
