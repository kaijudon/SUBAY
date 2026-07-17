from django.urls import path, reverse
from django_otp.admin import OTPAdminSite

# Front-end 4 (issue #5): the outcome-critical (four-eyes) models. Their
# entered-but-unverified rows are exactly what the Reviewing Clinician worklist
# surfaces; the same set the RBAC change-grant keys on (migration 0019).
OUTCOME_CRITICAL = ["cmvserology", "druglevel", "rejectionepisode", "genotypecall"]

# Front-end 5 (issue #6): the models a Safety Monitor ACTS on off a flagged QNAT
# row — logging a release-event (which clears the flag) or recording a protocol
# deviation / SAE. The release-timeliness worklist gates on the add permission
# over these, the same perm-not-group-name approach as OUTCOME_CRITICAL above.
SAFETY_ACTION_MODELS = ["releaseevent", "protocoldeviation"]

# Front-end 3 (issue #3): the admin index is grouped by STUDY WORKFLOW, in the
# order the operator works, instead of one flat alphabetical wall. Membership is
# by model object_name; ordering WITHIN a section is the listed order (work
# order), not alphabetical. Pure presentation on the site — no model moves app,
# no schema change. Any registered model not named here (auth/otp management
# models, or a future model) still surfaces under "Administration" so nothing
# becomes unreachable.
WORKFLOW_SECTIONS = [
    ("Subjects", ["Recipient", "Donor"]),
    ("Visit spine", ["RecipientVisit", "DonorVisit", "ClosureDay"]),
    ("Labs", [
        "CMVSerology", "CMVQuantitative", "TBNKPanel", "RenalFunction", "DrugLevel",
        "MedicationCourse", "RejectionEpisode", "Hospitalization", "OtherCondition",
    ]),
    ("Biobank ledger", ["Aliquot", "ThawEvent", "ConsumptionEvent", "SequencingAliquot"]),
    ("Genotyping", [
        "PipelineRun", "GenotypingResult", "GenotypeCall", "QpcrDetail",
        "QpcrProbeReading", "SangerDetail", "ReferenceSet", "ConcordancePair",
    ]),
    ("Safety", ["ReleaseEvent", "ProtocolDeviation"]),
]


class SubayAdminSite(OTPAdminSite):
    """The data-entry interface. OTPAdminSite enforces TOTP on every login.

    Defined in its own module (not admin.py) so resolving the lazy default_site
    never re-enters the module that performs @admin.register — which would orphan
    registrations on a throwaway site instance.
    """

    site_header = "SUBAY"
    site_title = "SUBAY"
    index_title = "CMV / Kidney-Transplant Research Database"

    def _section(self, name, models):
        return {
            "name": name,
            "app_label": name.lower().replace(" ", "_"),
            "app_url": "",  # synthetic group — no per-app index to link to
            "has_module_perms": True,
            "models": models,
        }

    # --- Front-end 4 (issue #5): Reviewing Clinician verification worklist ---

    def _can_verify(self, request):
        """True when the user may verify at least one outcome-critical model.
        Gating on the change permission (not a hardcoded group name) keeps role
        scoping as pure Django perms: the reviewing_clinician Group is granted
        change on these models (0019), the view-only analyst is not — so the
        worklist surfaces for the reviewer and stays hidden from the analyst
        without any bespoke role code."""
        return any(
            request.user.has_perm(f"registry.change_{model}")
            for model in OUTCOME_CRITICAL
        )

    # --- Front-end 5 (issue #6): Safety Monitor release-timeliness worklist ---

    def _can_monitor_safety(self, request):
        """True when the user may record a release-event or protocol deviation —
        the Safety Monitor function. Gates on the add permission (pure Django
        perms, no hardcoded group name): the entry/safety role can act, the
        view-only analyst and the reviewing clinician (who has no add on these)
        cannot, so the worklist stays scoped to who can work it."""
        return any(
            request.user.has_perm(f"registry.add_{model}")
            for model in SAFETY_ACTION_MODELS
        )

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "verification-worklist/",
                self.admin_view(self.verification_worklist_view),
                name="verification_worklist",
            ),
            path(
                "safety-worklist/",
                self.admin_view(self.safety_worklist_view),
                name="safety_worklist",
            ),
        ]
        # custom URLs first so the named route resolves before any catch-all.
        return custom + urls

    def safety_worklist_view(self, request):
        """The standing O4 release surface: exactly the QNAT rows flagged
        release_overdue (high-viral-load OR symptomatic, no timely release),
        computed from stored data via the QuerySet standing query — so threshold
        and window come from safety.py's named constants, never inline magic. Each
        flagged row deep-links to log a release-event (which clears the flag) and
        to record a protocol deviation / SAE (dual-track). admin_view() enforced
        login + staff + TOTP; this adds the safety-action permission."""
        from django.apps import apps
        from django.core.exceptions import PermissionDenied
        from django.template.response import TemplateResponse

        if not self._can_monitor_safety(request):
            raise PermissionDenied

        model = apps.get_model("registry", "cmvquantitative")
        release_add = reverse("admin:registry_releaseevent_add")
        deviation_add = reverse("admin:registry_protocoldeviation_add")
        rows = []
        for qnat in model.objects.overdue_release_flags():
            rows.append({
                "label": str(qnat),
                "recipient": qnat.recipient_visit.recipient if qnat.recipient_visit else None,
                "value": qnat.value,
                "severity_tier": qnat.severity_tier,
                "drawn_date": qnat.drawn_date,
                "change_url": reverse("admin:registry_cmvquantitative_change", args=[qnat.pk]),
                # deep-link the FK-anchored add forms via the ?quantitative= param
                "release_url": f"{release_add}?quantitative={qnat.pk}",
                "deviation_url": f"{deviation_add}?quantitative={qnat.pk}",
            })

        context = {
            **self.each_context(request),
            "title": "Release-timeliness worklist",
            "rows": rows,
            "total": len(rows),
        }
        return TemplateResponse(
            request, "admin/registry/safety_worklist.html", context
        )

    def verification_worklist_view(self, request):
        """One queue of exactly the entered-but-unverified outcome-critical rows,
        each linking to its change page (where the verification fields wait). A
        verified row (is_verified=True) is excluded by construction. admin_view()
        already enforced login + staff + TOTP; this adds the verify permission."""
        from django.apps import apps
        from django.core.exceptions import PermissionDenied
        from django.template.response import TemplateResponse

        if not self._can_verify(request):
            raise PermissionDenied

        groups = []
        total = 0
        for label in OUTCOME_CRITICAL:
            model = apps.get_model("registry", label)
            rows = []
            for obj in model.objects.filter(is_verified=False).order_by("pk"):
                rows.append({
                    "label": str(obj),
                    "entered_by": obj.entered_by,
                    "url": reverse(
                        f"admin:registry_{label}_change", args=[obj.pk]
                    ),
                })
            total += len(rows)
            groups.append({
                "title": model._meta.verbose_name_plural,
                "changelist_url": reverse(f"admin:registry_{label}_changelist"),
                "rows": rows,
            })

        context = {
            **self.each_context(request),
            "title": "Verification worklist",
            "groups": groups,
            "total": total,
        }
        return TemplateResponse(
            request, "admin/registry/verification_worklist.html", context
        )

    def get_app_list(self, request, app_label=None):
        """Regroup the index by workflow section. Role scoping is inherited:
        _build_app_dict already drops models the user has no permission for, so a
        section with no permitted models is simply not emitted — the landing
        shows only the sections the user's Group can act on (US#31)."""
        # Leave the per-app index (app_label set) on the default behavior; only
        # the main landing (app_label is None) is regrouped.
        if app_label is not None:
            return super().get_app_list(request, app_label)

        app_dict = self._build_app_dict(request)
        by_name = {}
        for app in app_dict.values():
            for model in app["models"]:
                by_name[model["object_name"]] = model

        app_list = []
        placed = set()
        for section, names in WORKFLOW_SECTIONS:
            models = [by_name[n] for n in names if n in by_name]
            placed.update(n for n in names if n in by_name)
            if models:
                app_list.append(self._section(section, models))

        # Worklists: synthetic index rows (same shape the template renders real
        # models as) linking to the queue views. Each rides the SAME permission
        # gate as its view, so a link never appears for a user the view forbids.
        review = []
        if self._can_verify(request):
            review.append({
                "name": "Verification worklist",
                "object_name": "VerificationWorklist",
                "perms": {"add": False, "change": True, "delete": False, "view": True},
                "admin_url": reverse("admin:verification_worklist"),
                "add_url": None,
                "view_only": True,
            })
        if self._can_monitor_safety(request):
            review.append({
                "name": "Release-timeliness worklist",
                "object_name": "SafetyWorklist",
                "perms": {"add": False, "change": True, "delete": False, "view": True},
                "admin_url": reverse("admin:safety_worklist"),
                "add_url": None,
                "view_only": True,
            })
        if review:
            app_list.append(self._section("Review", review))

        leftovers = [m for n, m in by_name.items() if n not in placed]
        if leftovers:
            leftovers.sort(key=lambda m: m["name"])
            app_list.append(self._section("Administration", leftovers))
        return app_list
