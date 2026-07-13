from django_otp.admin import OTPAdminSite

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


class RenovaAdminSite(OTPAdminSite):
    """The data-entry interface. OTPAdminSite enforces TOTP on every login.

    Defined in its own module (not admin.py) so resolving the lazy default_site
    never re-enters the module that performs @admin.register — which would orphan
    registrations on a throwaway site instance.
    """

    site_header = "RENOVA"
    site_title = "RENOVA"
    index_title = "RENal transplant Observational Viral Archive"

    def _section(self, name, models):
        return {
            "name": name,
            "app_label": name.lower().replace(" ", "_"),
            "app_url": "",  # synthetic group — no per-app index to link to
            "has_module_perms": True,
            "models": models,
        }

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

        leftovers = [m for n, m in by_name.items() if n not in placed]
        if leftovers:
            leftovers.sort(key=lambda m: m["name"])
            app_list.append(self._section("Administration", leftovers))
        return app_list
