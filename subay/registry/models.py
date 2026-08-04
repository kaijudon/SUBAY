"""SUBAY registry models — Slice 0 walking skeleton.

The abstract BaseSubject shares identity columns into concrete Recipient/Donor
without emitting its own table. Derived clinical values (age, risk_stratum,
is_positive) are @property and never stored, so a stored fact and its computed
value can never silently disagree.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords

from .attribution import (
    CONCORDANCE_CALLS,
    SUPERINFECTION_STATUSES,
    counted_for_strain_identity,
    grade_concordance,
)
from .episodes import (
    SEVERITY_TIERS,
    EpisodePoint,
    derive_episodes,
    summarize_episodes,
)
from .resistance import (
    RESISTANCE_LOCI,
    RESISTANCE_TIERS,
    is_active_virological_failure,
    return_of_results,
    rollup_by_locus,
)
from . import safety
from .safety import RELEASE_THRESHOLD_IU_ML, SYMPTOMATIC_TIERS
from .scheduling import TIMEPOINT_OFFSETS, ClosureDayLike, first_operating_day
from .serology_ranges import (
    REAGENT_GENERATION_CHOICES,
    VALID_GENERATIONS,
    generation_for,
    interpret_igg,
    interpret_igm,
    serostatus_from,
)
from .validators import subject_id_validator

SEX_CHOICES = [("M", "Male"), ("F", "Female")]
SEROSTATUS_CHOICES = [("POS", "Positive"), ("NEG", "Negative")]
INDUCTION_AGENT_CHOICES = [("atg", "ATG"), ("basiliximab", "Basiliximab"), ("none", "None")]
DONOR_TYPE_CHOICES = [("living", "Living"), ("deceased", "Deceased")]
TIMEPOINT_LABEL_CHOICES = [(k, k) for k in TIMEPOINT_OFFSETS]
CLOSURE_REASON_CHOICES = [
    ("annexed_holiday", "Annexed holiday"),
    ("emergency_closure", "Emergency closure"),
]
COMPLETION_STATUS_CHOICES = [("completed", "Completed"), ("missed_visit", "Missed visit")]
# Patient-level cohort disposition (US 20) — the seven LOCKED CONSORT values, in
# PRD order. Distinct from the 2-value RecipientVisit.completion_status above:
# same column name, different model, no Python collision. Hand-entered by the
# Data Manager (a disposition is a clinical judgement, not derivable from visits).
RECIPIENT_COMPLETION_STATUS_CHOICES = [
    ("enrolled", "Enrolled"),
    ("withdrawn", "Withdrawn"),
    ("died", "Died"),
    ("lost_to_followup", "Lost to follow-up"),
    ("graft_loss", "Graft loss"),
    ("missed_visit", "Missed visit"),
    ("completed", "Completed"),
]
# A result is either reported (carries a value) or a missing observation (a
# QC/lab failure). A missing observation is a result-level fact only — it never
# touches the recipient's completion_status.
RESULT_STATUS_CHOICES = [("reported", "Reported"), ("missing", "Missing")]


def _result_status_field(help_text="reported = a value was obtained; missing = QC/lab failure (no value)."):
    """Shared `result_status` field for lab-result models: distinguishes a real
    value from a QC/lab failure. A missing observation never alters cohort
    disposition. Factory (not an abstract base) so each model keeps its own field
    ordering and the generated field is byte-identical (no migration churn)."""
    return models.CharField(
        max_length=8,
        choices=RESULT_STATUS_CHOICES,
        default="reported",
        help_text=help_text,
    )


def _status_matches_value_constraint(name, value_field="value", status_field="result_status"):
    """CheckConstraint: a 'reported' status requires a non-null value; a 'missing'
    status forbids one. Shared across lab-result models — the value/status column
    names vary, so the rule lives in one place rather than copy-pasted per model."""
    return models.CheckConstraint(
        name=name,
        condition=(
            models.Q(**{status_field: "reported", f"{value_field}__isnull": False})
            | models.Q(**{status_field: "missing", f"{value_field}__isnull": True})
        ),
    )


class VerificationMixin(models.Model):
    """Four-eyes verification for outcome-critical rows (US 68): a finalized
    (`is_verified`) row needs a `verified_by` who DIFFERS from `entered_by`, plus a
    `verified_at` timestamp. Enforced at BOTH layers — clean() for a friendly
    admin/forms error and a DB CheckConstraint for an unbreakable guarantee on the
    shell/ingest bare-save path — mirroring the GenotypeCall/ConsumptionEvent
    dual-guard. Fields are nullable (DEC-023): the gate bites ONLY when
    is_verified=True, so the many existing un-attributed fixtures keep passing.

    Concrete models spread `verification_constraints(prefix)` into their own
    Meta.constraints (DEC-024: an abstract base cannot carry per-model-unique
    constraint names, and abstract FKs need a `%(class)s_…` related_name)."""

    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="%(class)s_entered",
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="%(class)s_verified",
    )
    verified_at = models.DateField(null=True, blank=True)
    is_verified = models.BooleanField(default=False)

    class Meta:
        abstract = True

    @staticmethod
    def verification_constraints(prefix):
        """The two CheckConstraints enforcing the four-eyes gate at the DB layer.
        Both pass freely while is_verified=False; once verified they require a full,
        differing attribution. `verified_at` (a DateField) is the drawn_date leak
        shape — it must NEVER enter an export *_COLUMNS list."""
        return [
            models.CheckConstraint(
                name=f"{prefix}_verified_requires_verifier",
                condition=(
                    models.Q(is_verified=False)
                    | models.Q(
                        entered_by__isnull=False,
                        verified_by__isnull=False,
                        verified_at__isnull=False,
                    )
                ),
            ),
            models.CheckConstraint(
                name=f"{prefix}_verifier_differs_when_verified",
                condition=(
                    models.Q(is_verified=False)
                    | ~models.Q(verified_by=models.F("entered_by"))
                ),
            ),
        ]

    def clean(self):
        super().clean()
        if not self.is_verified:
            return
        if self.entered_by_id is None or self.verified_by_id is None or self.verified_at is None:
            raise ValidationError(
                "A verified row requires entered_by, verified_by and verified_at."
            )
        if self.entered_by_id == self.verified_by_id:
            raise ValidationError(
                "The verifier must differ from the editor (entered_by != verified_by)."
            )


class AppendOnlyQuerySet(models.QuerySet):
    """Blocks `QuerySet.update()` from rewriting a model's declared write-once
    fields. clean() guards the normal save path, but a bulk `.update()` skips
    clean(); a model lists `IMMUTABLE_FIELDS` and this refuses to touch them.
    (A raw SQL UPDATE still bypasses this — only a DB trigger covers that.)"""

    def update(self, **kwargs):
        protected = set(getattr(self.model, "IMMUTABLE_FIELDS", ())) & set(kwargs)
        if protected:
            raise ValueError(
                f"{self.model.__name__}: {sorted(protected)} are append-only and "
                "cannot be changed via .update()."
            )
        return super().update(**kwargs)


DRUG_ANALYTE_CHOICES = [("tacrolimus", "Tacrolimus"), ("everolimus", "Everolimus")]
# Slice 08 clinical-event vocabularies. Structured (choices), never free text, so a
# mandated prophylaxis can never masquerade as a clinical response at analysis.
DRUG_CLASS_CHOICES = [("antiviral", "Antiviral"), ("immunosuppressant", "Immunosuppressant")]
DOSE_UNIT_CHOICES = [("mg", "mg"), ("g", "g"), ("mg_kg", "mg/kg"), ("mg_m2", "mg/m²")]
FREQUENCY_CHOICES = [
    ("qd", "Once daily"), ("bid", "Twice daily"), ("tid", "Three times daily"),
    ("qod", "Every other day"), ("weekly", "Weekly"),
]
COURSE_TYPE_CHOICES = [("prophylaxis", "Prophylaxis"), ("treatment", "Treatment")]
IS_CHANGE_DIRECTION_CHOICES = [("reduction", "Reduction"), ("intensification", "Intensification")]
EARLY_DISCONT_REASON_CHOICES = [
    ("toxicity", "Toxicity"), ("intolerance", "Intolerance"),
    ("cost", "Cost"), ("other", "Other"),
]
REJECTION_TYPE_CHOICES = [("tcmr", "TCMR"), ("amr", "AMR"), ("mixed", "Mixed")]
BANFF_GRADE_CHOICES = [
    ("borderline", "Borderline"),
    ("ia", "IA"), ("ib", "IB"), ("iia", "IIA"), ("iib", "IIB"), ("iii", "III"),
    ("amr_active", "Active AMR"), ("amr_chronic", "Chronic active AMR"),
]
DISPOSITION_CHOICES = [
    ("discharged_home", "Discharged home"), ("transferred", "Transferred"),
    ("died", "Died"), ("against_advice", "Against medical advice"),
]
# Slice 09 biobank-matrix vocabulary — provisional, structured (never free text)
# so a sample type can't drift into an identifier. Deferred: the full label format
# CMVKT-SUBJID-VISIT-MATRIX-TYPE (on standby, not exported this slice).
MATRIX_CHOICES = [
    ("plasma", "Plasma"), ("serum", "Serum"), ("pbmc", "PBMC"),
    ("whole_blood", "Whole blood"), ("urine", "Urine"),
]
# Clinical Kotton-2018 severity, sourced from the pure deriver so the stored
# choices can never drift from the tiers the episode logic ranks.
SEVERITY_TIER_CHOICES = [(t, t.capitalize()) for t in SEVERITY_TIERS]
VISIT_SHIFT_CAP_DAYS = 3
# Slice 10 genotyping vocabularies — LOCKED, structured (never free text) so a
# call code can't drift. Sanger loci carry R/F/N (Resolved / Failed-QC /
# No-amplicon); qPCR per-probe readings carry P/N/I (Positive / Negative /
# Indeterminate) and roll up to single / mixed / untyped.
ASSAY_TYPE_CHOICES = [("sanger", "Sanger"), ("qpcr", "qPCR")]
SANGER_CALL_CHOICES = [("R", "Resolved"), ("F", "Failed-QC"), ("N", "No-amplicon")]
QPCR_PROBE_CHOICES = [("P", "Positive"), ("N", "Negative"), ("I", "Indeterminate")]
# Slice 11 source-attribution & concordance vocabularies. The four concordance
# tiers come from the pure grader so the stored choices can never drift from what
# grade_concordance returns (the SEVERITY_TIER_CHOICES precedent). Superinfection
# is flagged candidate vs confirmed; only confirmed upgrades source_label.
CONCORDANCE_CALL_CHOICES = [(t, t.replace("_", " ").capitalize()) for t in CONCORDANCE_CALLS]
SUPERINFECTION_STATUS_CHOICES = [(s, s.capitalize()) for s in SUPERINFECTION_STATUSES]
# Slice 12 resistance vocabularies — the two reported loci (UL97/UL54) and the
# three interpretive tiers come from the pure resistance module so the stored
# choices can never drift from what the rollup/flag logic reads (the
# SEVERITY_TIER_CHOICES precedent). Status reuses SANGER_CALL_CHOICES (R/F/N).
RESISTANCE_LOCUS_CHOICES = [(loc, loc) for loc in RESISTANCE_LOCI]
RESISTANCE_TIER_CHOICES = [(t, t.capitalize()) for t in RESISTANCE_TIERS]


def _age_at(subject, ref_date):
    """Whole years from a subject's DOB to ref_date (same convention as
    Recipient.age). None when either input is missing."""
    if subject is None or not subject.date_of_birth or not ref_date:
        return None
    dob = subject.date_of_birth
    return ref_date.year - dob.year - ((ref_date.month, ref_date.day) < (dob.month, dob.day))


class BaseSubject(models.Model):
    """Shared identity for every study subject. Abstract — emits no table."""

    subject_id = models.CharField(
        max_length=12,
        primary_key=True,
        validators=[subject_id_validator],
        help_text="Pseudonym [S|D]CMV[R|D][NN], e.g. SCMVR07. Never a name/MRN/address.",
    )
    date_of_birth = models.DateField()
    sex = models.CharField(max_length=1, choices=SEX_CHOICES)

    class Meta:
        abstract = True

    def __str__(self):
        return self.subject_id


class Recipient(BaseSubject):
    """A kidney-transplant recipient. kt_date is the day-0 anchor for de-id."""

    kt_date = models.DateField(help_text="Transplant date — day 0 for de-identified offsets.")
    donor_serostatus = models.CharField(
        max_length=3,
        choices=SEROSTATUS_CHOICES,
        null=True,
        blank=True,
        help_text="Authoritative donor CMV serostatus clinicians acted on at transplant.",
    )
    recipient_serostatus = models.CharField(
        max_length=3,
        choices=SEROSTATUS_CHOICES,
        null=True,
        blank=True,
        help_text="Pre-KT recipient CMV serostatus.",
    )
    donor = models.ForeignKey(
        "Donor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="recipients",
        help_text="Paired donor (optional — record may not be entered yet). PROTECT.",
    )
    has_diabetes = models.BooleanField(
        null=True, blank=True, help_text="Three-state: True / False / Unknown (not asked)."
    )
    has_hypertension = models.BooleanField(
        null=True, blank=True, help_text="Three-state: True / False / Unknown (not asked)."
    )
    dialysis_vintage_months = models.PositiveIntegerField(null=True, blank=True)
    induction_agent = models.CharField(
        max_length=12,
        choices=INDUCTION_AGENT_CHOICES,
        null=True,
        blank=True,
        help_text="atg / basiliximab / none. 'none' asserts absence; null = not recorded.",
    )
    completion_status = models.CharField(
        max_length=16,
        choices=RECIPIENT_COMPLETION_STATUS_CHOICES,
        default="enrolled",
        help_text="Cohort disposition for CONSORT (US 20). Hand-entered; never derived. "
        "A lab/QC failure must NOT change this.",
    )
    sequencing_included = models.BooleanField(
        default=True,
        help_text="In the Obj 5 all-sequenced denominator regardless of cohort disposition, "
        "so non-completers' samples stay counted.",
    )
    history = HistoricalRecords()

    @property
    def age(self):
        """Whole years at transplant. Derived from DOB, never stored."""
        if not self.date_of_birth or not self.kt_date:
            return None
        dob, ref = self.date_of_birth, self.kt_date
        return ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))

    @property
    def risk_stratum(self):
        """CMV risk from D/R serostatus (Obj 5 D±/R±). Derived, never stored."""
        d, r = self.donor_serostatus, self.recipient_serostatus
        if not d or not r:
            return None
        if d == "POS" and r == "NEG":
            return "high"  # D+/R-
        if r == "POS":
            return "intermediate"  # R+ (D+/R+ or D-/R+)
        return "low"  # D-/R-

    @property
    def pre_kt_igg_serostatus(self):
        """R+/R- computed ONCE from the pre_kt visit's IgG serology, read against
        the reagent generation that produced it. The canonical pre-KT serostatus
        both Obj 4a stratification and Obj 5 attribution consume — derived, never
        stored, so the two objectives can never read disagreeing values.

        None when there is no pre_kt visit, when its IgG result is missing, or
        when the reading is EQUIVOCAL. The grayzone is not a third category: an
        equivocal recipient is undetermined until a repeat draw resolves it, and
        is treated exactly as an absent draw is."""
        visit = self.visits.filter(timepoint_label="pre_kt").first()
        if visit is None:
            return None
        s = visit.serologies.first()
        if s is None:
            return None
        return serostatus_from(s.igg_interpretation)

    @property
    def has_donor_serostatus_mismatch(self):
        """Flag (never overwrite) a clash between the recorded donor serostatus
        and the paired donor's own serology. Surfaces for hand reconciliation;
        both stored facts stay intact.

        Three answers, not two. None means NOT COMPARABLE — no paired donor, no
        recorded serostatus, or a donor serology that yielded no baseline (absent
        or equivocal). It is deliberately distinct from False, which asserts that
        the two sides WERE compared and agreed. Collapsing the two would present
        the weakest possible donor evidence to a reviewer as a clean all-clear,
        which the equivocal band makes a common case rather than a rare one."""
        if self.donor_id is None:
            return None
        donor_status = self.donor.baseline_serostatus
        if not self.donor_serostatus or not donor_status:
            return None
        return self.donor_serostatus != donor_status

    def _reported_qnat_points(self):
        """Ordered EpisodePoints from this recipient's REPORTED viral-load draws,
        in day-offset space (drawn_date - kt_date). Donor-attached QNAT (no kt
        anchor) and missing observations (a QC failure is not clearance) are
        excluded, so a calendar date never reaches the deriver."""
        qs = CMVQuantitative.objects.filter(
            recipient_visit__recipient=self, result_status="reported"
        ).order_by("drawn_date", "pk")
        return [
            EpisodePoint((q.drawn_date - self.kt_date).days, q.value, q.severity_tier)
            for q in qs
        ]

    @property
    def cmv_episodes(self):
        """Derived CMV episodes (Topic #4 rules). Computed at read, never stored."""
        return derive_episodes(self._reported_qnat_points())

    @property
    def cmv_episode_summary(self):
        """Subject-level episode variables for the SAP, or None when the recipient
        has no reported QNAT series to anchor person-time/censoring."""
        points = self._reported_qnat_points()
        if not points:
            return None
        days = [p.day for p in points]
        return summarize_episodes(self.cmv_episodes, min(days), max(days))

    @property
    def has_positive_qnat(self):
        """Any REPORTED viral-load draw on this recipient at/above the assay LoD
        (34.5 IU/mL) — the SAME positivity bar the episode deriver uses (DEC-023),
        so attribution and episodes can never disagree about what 'positive' means."""
        return CMVQuantitative.objects.filter(
            recipient_visit__recipient=self,
            result_status="reported",
            value__gte=CMVQuantitative.LOD,
        ).exists()

    @property
    def source_label(self):
        """Exactly one flat source label by the LOCKED priority
        donor-derived > primary > reactivation (AC1), or None when no CMV event is
        attributable. donor-derived is the reviewer-set tier (a ConcordancePair with
        superinfection_status == 'confirmed', DEC-021); primary is the computed
        QNAT+-in-an-R− trigger (seroconversion never gates, AC2)."""
        if self.concordance_pairs.filter(superinfection_status="confirmed").exists():
            return "donor_derived"
        if not self.has_positive_qnat:
            return None
        serostatus = self.pre_kt_igg_serostatus
        if serostatus == "NEG":
            return "primary"
        if serostatus == "POS":
            return "reactivation"
        return None  # serostatus unknown -> not attributable

    @property
    def resistance_rollup(self):
        """Per-locus UL97/UL54 surveillance rollup for this subject (both loci
        keyed separately, derived, never stored, never pooled — AC2). Reads the
        resistance calls riding this recipient's tube→result chain."""
        calls = ResistanceCall.objects.filter(
            result__aliquot__recipient_visit__recipient=self
        )
        return rollup_by_locus(
            [(c.locus, c.status, c.established_resistance_present) for c in calls]
        )


class Donor(BaseSubject):
    """A living/deceased donor — thin, at most one baseline serology, one draw."""

    donor_type = models.CharField(
        max_length=8, choices=DONOR_TYPE_CHOICES, null=True, blank=True
    )
    relation = models.CharField(
        max_length=40, null=True, blank=True, help_text="Optional relation to recipient."
    )
    history = HistoricalRecords()

    @property
    def baseline_serostatus(self):
        """POS/NEG from the donor's single serology, read against the reagent
        generation that produced it. Derived — never stored, so it can't disagree
        with the lab value.

        None when there is no draw, when the result is missing, or when the
        reading is EQUIVOCAL. A donor has at most one baseline serology, so an
        equivocal donor result is terminal: there is no second row to resolve it
        and the donor simply has no established baseline serostatus."""
        s = self.serologies.first()
        if s is None:
            return None
        return serostatus_from(s.igg_interpretation)


class ClosureDay(models.Model):
    """A recognized clinic/lab closure day — the calendar the forward-shift SOP
    reads (DEC-008). Editable by the Data Manager, auditable via history. A day
    may close only clinic OR only lab; a visit needs BOTH operating, so either
    flag forces the shift."""

    date = models.DateField(unique=True)
    reason = models.CharField(max_length=20, choices=CLOSURE_REASON_CHOICES)
    reference = models.CharField(
        max_length=120, blank=True, help_text="Annex/clause/memo cite. Free text — never exported."
    )
    closes_clinic = models.BooleanField(default=True)
    closes_lab = models.BooleanField(default=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.date} ({self.reason})"


class RecipientVisit(models.Model):
    """One protocol timepoint for a recipient. The genuine inputs are stored
    (`timepoint_label`, `actual_visit_date`, `completion_status`); every
    scheduling fact (`nominal_day`, `closure_*`, `shift_days_from_nominal`) is a
    derived `@property` over kt_date + the ClosureDay calendar (DEC-009), so a
    stored value can never drift from what the calendar implies."""

    recipient = models.ForeignKey(Recipient, on_delete=models.CASCADE, related_name="visits")
    timepoint_label = models.CharField(max_length=8, choices=TIMEPOINT_LABEL_CHOICES)
    actual_visit_date = models.DateField()
    completion_status = models.CharField(
        max_length=12, choices=COMPLETION_STATUS_CHOICES, default="completed"
    )
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.recipient_id} {self.timepoint_label} @ {self.actual_visit_date}"

    @property
    def nominal_day(self):
        """Protocol day-offset from kt_date for this timepoint."""
        return TIMEPOINT_OFFSETS[self.timepoint_label]

    @property
    def nominal_date(self):
        return self.recipient.kt_date + timedelta(days=self.nominal_day)

    @property
    def scheduled_date(self):
        """First day clinic AND lab both operate, on/after the nominal date."""
        return first_operating_day(self.nominal_date, ClosureDay.objects.all())

    @property
    def closure_shifted(self):
        return self.scheduled_date != self.nominal_date

    def _closure_at_nominal(self):
        return ClosureDay.objects.filter(date=self.nominal_date).first()

    @property
    def closure_reason(self):
        c = self._closure_at_nominal()
        return c.reason if c else "none"

    @property
    def stretch_reference(self):
        c = self._closure_at_nominal()
        return c.reference if c else ""

    @property
    def shift_days_from_nominal(self):
        """Signed days the actual draw fell from the nominal protocol day. With
        `closure_reason` it separates forced-replacement (closure) from
        patient-initiated non-attendance for CONSORT."""
        return (self.actual_visit_date - self.nominal_date).days

    def clean(self):
        """+3-day cap (model layer, so shell + admin both honor it): an actual
        date more than 3 days past nominal is only legal when the visit is
        recorded `missed_visit` — there is no backward shift, no partial visit."""
        if self.shift_days_from_nominal > VISIT_SHIFT_CAP_DAYS and (
            self.completion_status != "missed_visit"
        ):
            raise ValidationError(
                f"actual_visit_date is {self.shift_days_from_nominal} days past nominal "
                f"(cap {VISIT_SHIFT_CAP_DAYS}); record it as completion_status='missed_visit'."
            )


class DonorVisit(models.Model):
    """Minimal donor draw record: a donor + a draw_date, nothing more. A donor
    gets NO recipient-grade timeline (no nominal_day/timepoint/closure shift)."""

    donor = models.ForeignKey(Donor, on_delete=models.CASCADE, related_name="visits")
    draw_date = models.DateField()
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.donor_id} @ {self.draw_date}"


class ExactlyOneParentMixin(models.Model):
    """Abstract base for lab-result models that attach to EXACTLY ONE parent —
    a RecipientVisit XOR a Donor. Subclasses declare the two FKs and the DB
    CheckConstraint; this centralizes the friendly clean() guard so the rule
    isn't copy-pasted per model. Subclasses with extra validation override
    clean() and call super().clean() first."""

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        has_visit = self.recipient_visit_id is not None
        has_donor = self.donor_id is not None
        if has_visit == has_donor:
            raise ValidationError(
                f"A {type(self).__name__} must attach to exactly one of "
                "recipient_visit or donor (not both, not neither)."
            )

    def _validate_value_matches_status(self, value):
        """A reported result carries a value; a missing observation does not.
        Shared by subclasses (the value column varies) so it isn't copy-pasted."""
        if self.result_status == "reported" and value is None:
            raise ValidationError("A reported result must carry a value.")
        if self.result_status == "missing" and value is not None:
            raise ValidationError("A missing observation must not carry a value.")


class CMVSerology(ExactlyOneParentMixin, VerificationMixin):
    """One lab result attached to EXACTLY ONE parent: a recipient visit OR a donor.

    Enforced twice: clean() for a friendly admin error, a DB CheckConstraint for an
    unbreakable guarantee on every write path. value is Snibe Maglumi 600 AU/mL;
    is_positive is derived at the 2.0 AU/mL binary threshold.
    """

    POSITIVE_THRESHOLD = Decimal("2.0")

    recipient_visit = models.ForeignKey(
        RecipientVisit,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="serologies",
    )
    donor = models.ForeignKey(
        Donor,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="serologies",
    )
    value = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="IgG channel. Snibe Maglumi 600 AU/mL. Null only when result_status='missing'.",
    )
    result_status = models.CharField(
        max_length=8,
        choices=RESULT_STATUS_CHOICES,
        default="reported",
        help_text="IgG channel. reported = a value was obtained; missing = QC/lab failure "
        "(no value). A missing observation never changes the recipient's completion_status.",
    )
    igm_value = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="IgM channel. Snibe Maglumi 600 AU/mL. Null only when igm_status='missing'.",
    )
    igm_status = models.CharField(
        max_length=8,
        choices=RESULT_STATUS_CHOICES,
        default="missing",
        help_text="IgM channel. Defaults 'missing' — an IgG-only draw has no IgM observation.",
    )
    drawn_date = models.DateField()
    reagent_generation = models.CharField(
        max_length=4,
        choices=REAGENT_GENERATION_CHOICES,
        blank=True,
        help_text="Assay reagent generation that produced this result. Leave blank "
        "to default from the draw date (2nd gen from 2026-06-03). Set it by hand "
        "only for a late-entered sample that was run on 1st-generation reagent.",
    )
    history = HistoricalRecords()

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="cmvserology_exactly_one_parent",
                condition=(
                    models.Q(recipient_visit__isnull=False, donor__isnull=True)
                    | models.Q(recipient_visit__isnull=True, donor__isnull=False)
                ),
            ),
            models.UniqueConstraint(
                name="cmvserology_at_most_one_per_donor",
                fields=["donor"],
                condition=models.Q(donor__isnull=False),
            ),
            _status_matches_value_constraint("cmvserology_value_matches_result_status"),
            _status_matches_value_constraint(
                "cmvserology_igm_value_matches_status", "igm_value", "igm_status"
            ),
            # The stored generation KEYS the band maps, so an unrecognized code
            # is not a cosmetic data-quality problem: every interpretation on the
            # row stops answering, taking the serology changelist, both derived
            # serostatuses and the export down with it. `choices` is form-level
            # and says nothing about the shell and ingest paths, which is exactly
            # where a mis-cased or legacy code arrives from. Blank is allowed
            # because it is the documented "default from the draw date" input;
            # effective_reagent_generation resolves it to a real code.
            models.CheckConstraint(
                name="cmvserology_known_reagent_generation",
                condition=models.Q(reagent_generation__in=sorted(VALID_GENERATIONS) + [""]),
            ),
            *VerificationMixin.verification_constraints("cmvserology_verification"),
        ]

    @property
    def is_positive(self):
        if self.value is None:
            return None
        return self.value >= self.POSITIVE_THRESHOLD

    @property
    def igm_positive(self):
        """IgM positivity at the SAME locked 2.0 AU/mL single cutoff. Derived,
        never stored — no equivocal band, only True / False / None (not measured)."""
        if self.igm_value is None:
            return None
        return self.igm_value >= self.POSITIVE_THRESHOLD

    @property
    def effective_reagent_generation(self):
        """The generation this row is read against: the stored one, or the one
        the draw date implies.

        None only on an UNSAVED row that has no draw date yet - the admin add
        form, where every field is still blank. save() fills the stored value, so
        a persisted row always answers. Guarding here rather than letting
        generation_for() compare None to a date, which crashed the visit change
        page when the serology inline rendered an empty form.
        """
        if self.reagent_generation:
            return self.reagent_generation
        if self.drawn_date is None:
            return None
        return generation_for(self.drawn_date)

    @property
    def igg_interpretation(self):
        """non_reactive / equivocal / reactive, read against THIS ROW's reagent
        generation. None means not measured, not a fourth clinical answer."""
        generation = self.effective_reagent_generation
        if generation is None:
            return None
        return interpret_igg(self.value, generation)

    @property
    def igm_interpretation(self):
        generation = self.effective_reagent_generation
        if generation is None:
            return None
        return interpret_igm(self.igm_value, generation)

    def save(self, *args, **kwargs):
        """Fill the reagent generation from the draw date when it was left blank.

        This model otherwise puts every rule in clean() plus a CheckConstraint,
        and a save() override is a departure from that. It earns its place: the
        generation has to be right on EVERY write path, including the bare-save
        and loaddata paths clean() never sees, and unlike the other rules this
        one supplies a value rather than rejecting one, which a CheckConstraint
        cannot do. Explicitly-set values are never touched, so a late-entered
        first-generation sample keeps the generation a human chose for it.
        """
        if not self.reagent_generation and self.drawn_date:
            self.reagent_generation = generation_for(self.drawn_date)
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self._validate_value_matches_status(self.value)
        if self.igm_status == "reported" and self.igm_value is None:
            raise ValidationError("A reported IgM result must carry a value.")
        if self.igm_status == "missing" and self.igm_value is not None:
            raise ValidationError("A missing IgM observation must not carry a value.")
        if self.reagent_generation and self.reagent_generation not in VALID_GENERATIONS:
            raise ValidationError(
                {
                    "reagent_generation": (
                        f"Unknown reagent generation {self.reagent_generation!r}. "
                        f"Use one of: {', '.join(sorted(VALID_GENERATIONS))}, or leave "
                        "blank to default from the draw date."
                    )
                }
            )


# Slice 14 — protocol-deviation kinds (a missed or late safety release). Two
# values only, enforced via choices; the structured signal carries the analyzable
# content (no free text exported).
DEVIATION_TYPE_CHOICES = [("late_release", "Late release"), ("missed_release", "Missed release")]


class CMVQuantitativeQuerySet(models.QuerySet):
    """Standing-query surface for the safety release-timeliness flag (Slice 14)."""

    def requiring_release(self):
        """REPORTED, recipient-attached draws that need a logged release-event:
        high-viral-load OR symptomatic. Donor-attached draws (no kt anchor) are
        excluded, mirroring Recipient._reported_qnat_points."""
        return self.filter(
            result_status="reported", recipient_visit__isnull=False
        ).filter(
            models.Q(value__gte=RELEASE_THRESHOLD_IU_ML)
            | models.Q(severity_tier__in=SYMPTOMATIC_TIERS)
        )

    def overdue_release_flags(self):
        """The standing query (AC1/AC4): the requiring-release draws whose release
        is overdue, computed purely from stored value/severity_tier/ReleaseEvent
        rows — never a hand-maintained list."""
        qs = self.requiring_release().prefetch_related("release_events")
        return [q for q in qs if q.release_overdue]


class CMVQuantitative(ExactlyOneParentMixin):
    """One CMV viral-load measurement, stored LONG — one row per result so a
    patient's repeating draws form an ordered series (Meta.ordering by drawn_date)
    the episode deriver (slice 07) consumes, never forced into a fixed shape.

    Attaches to EXACTLY ONE parent (recipient visit OR donor), enforced twice like
    CMVSerology: clean() for a friendly admin error, a DB CheckConstraint for an
    unbreakable guarantee. value is COBAS 5000 IU/mL; a result below LoQ is still a
    row (long shape, no clamping decision needed this slice)."""

    ASSAY = "COBAS 5000"
    LOD = Decimal("34.5")  # limit of detection
    LOQ = Decimal("34.5")  # limit of quantitation (== LoD for this assay)

    recipient_visit = models.ForeignKey(
        RecipientVisit,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="quantitatives",
    )
    donor = models.ForeignKey(
        Donor,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="quantitatives",
    )
    value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="COBAS 5000 IU/mL. Null only when result_status='missing'.",
    )
    result_status = models.CharField(
        max_length=8,
        choices=RESULT_STATUS_CHOICES,
        default="reported",
        help_text="reported = a value was obtained; missing = QC/lab failure (no value). "
        "A missing observation never changes the recipient's completion_status.",
    )
    severity_tier = models.CharField(
        max_length=12,
        choices=SEVERITY_TIER_CHOICES,
        default="asymptomatic",
        help_text="Clinical Kotton-2018 tier (asymptomatic/syndrome/disease) for this draw. "
        "Symptom-based, NOT value-derived; an episode's tier = the max among its members.",
    )
    drawn_date = models.DateField()
    history = HistoricalRecords()

    objects = CMVQuantitativeQuerySet.as_manager()

    class Meta:
        # Chronological so the episode deriver reads an ordered series.
        ordering = ["drawn_date", "pk"]
        constraints = [
            models.CheckConstraint(
                name="cmvquantitative_exactly_one_parent",
                condition=(
                    models.Q(recipient_visit__isnull=False, donor__isnull=True)
                    | models.Q(recipient_visit__isnull=True, donor__isnull=False)
                ),
            ),
            _status_matches_value_constraint("cmvquantitative_value_matches_result_status"),
        ]

    def clean(self):
        super().clean()
        self._validate_value_matches_status(self.value)

    # --- Slice 14: safety release-timeliness flags (derived, never stored) ---

    @property
    def requires_release(self):
        """High-viral-load OR symptomatic — needs a logged release-event (AC1)."""
        return safety.requires_release(self.value, self.severity_tier)

    @property
    def has_timely_release(self):
        """Any release logged inside the 24h (day-granular) window. Offsets are
        days from THIS draw, so timeliness needs no kt anchor."""
        released_offsets = [(e.released_date - self.drawn_date).days for e in self.release_events.all()]
        return safety.is_release_timely(0, released_offsets, safety.RELEASE_WINDOW_DAYS)

    @property
    def release_overdue(self):
        """The Safety-Monitor flag: a reported draw that requires a release and has
        no timely one. Only meaningful for a reported result (a missing observation
        is a QC failure, not an actionable result)."""
        if self.result_status != "reported":
            return False
        return self.requires_release and not self.has_timely_release


class TBNKPanel(ExactlyOneParentMixin):
    """One lymphocyte-subset panel, stored WIDE — the seven subsets are co-drawn
    in a single assay run, so they stay one row (wide-vs-long-by-variability).
    Each subset is two stored columns: absolute count (cells/µL) AND % lymphocytes.
    cd4_cd8_ratio is DERIVED (derive-don't-store), never a column.

    Attaches to EXACTLY ONE parent (recipient visit XOR donor), enforced twice
    like CMVQuantitative: clean() for a friendly admin error, a DB CheckConstraint
    for an unbreakable guarantee."""

    recipient_visit = models.ForeignKey(
        RecipientVisit,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="tbnk_panels",
    )
    donor = models.ForeignKey(
        Donor,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="tbnk_panels",
    )
    cd3_count = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="CD3+ absolute count, cells/µL.")
    cd3_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="CD3+ % of lymphocytes.")
    cd3_cd4_count = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="CD3+CD4+ absolute count, cells/µL.")
    cd3_cd4_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="CD3+CD4+ % of lymphocytes.")
    cd3_cd8_count = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="CD3+CD8+ absolute count, cells/µL.")
    cd3_cd8_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="CD3+CD8+ % of lymphocytes.")
    cd19_count = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="CD19+ absolute count, cells/µL.")
    cd19_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="CD19+ % of lymphocytes.")
    nk_count = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="NK CD3−CD16+CD56+ absolute count, cells/µL.")
    nk_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="NK CD3−CD16+CD56+ % of lymphocytes.")
    cd4_cd8_dp_count = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="CD4+CD8+ double-positive absolute count, cells/µL.")
    cd4_cd8_dp_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="CD4+CD8+ double-positive % of lymphocytes.")
    cd4_cd8_dn_count = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="CD4−CD8− double-negative absolute count, cells/µL.")
    cd4_cd8_dn_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="CD4−CD8− double-negative % of lymphocytes.")
    drawn_date = models.DateField()
    history = HistoricalRecords()

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="tbnkpanel_exactly_one_parent",
                condition=(
                    models.Q(recipient_visit__isnull=False, donor__isnull=True)
                    | models.Q(recipient_visit__isnull=True, donor__isnull=False)
                ),
            ),
        ]

    @property
    def cd4_cd8_ratio(self):
        """CD3+CD4+ count ÷ CD3+CD8+ count. Derived, never stored — None when
        either count is missing or the denominator is zero."""
        if self.cd3_cd4_count is None or not self.cd3_cd8_count:
            return None
        return self.cd3_cd4_count / self.cd3_cd8_count


class RenalFunction(ExactlyOneParentMixin):
    """One renal-function draw. Stores RAW serum creatinine only; eGFR is DERIVED
    via CKD-EPI 2021 race-free and never stored. Any lab-reported eGFR is IGNORED
    by giving it no column to live in — a stored-but-unused eGFR would invite a
    site-equation step-artifact at a multi-site join (US 28).

    Attaches to EXACTLY ONE parent (recipient visit XOR donor), enforced twice."""

    recipient_visit = models.ForeignKey(
        RecipientVisit,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="renal_functions",
    )
    donor = models.ForeignKey(
        Donor,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="renal_functions",
    )
    serum_creatinine_mg_dl = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Raw serum creatinine, mg/dL. Null only when result_status='missing'.",
    )
    result_status = _result_status_field()
    drawn_date = models.DateField()
    history = HistoricalRecords()

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="renalfunction_exactly_one_parent",
                condition=(
                    models.Q(recipient_visit__isnull=False, donor__isnull=True)
                    | models.Q(recipient_visit__isnull=True, donor__isnull=False)
                ),
            ),
            _status_matches_value_constraint(
                "renalfunction_value_matches_result_status", "serum_creatinine_mg_dl"
            ),
        ]

    @property
    def eGFR(self):
        """CKD-EPI 2021 race-free eGFR derived from stored creatinine. None when
        creatinine is missing or sex/age can't be resolved from the parent."""
        if self.serum_creatinine_mg_dl is None:
            return None
        subject = self.recipient_visit.recipient if self.recipient_visit_id else self.donor
        if subject is None:
            return None
        age = _age_at(subject, self.drawn_date)
        if age is None or not subject.sex:
            return None
        is_female = subject.sex == "F"
        kappa = 0.7 if is_female else 0.9
        alpha = -0.241 if is_female else -0.302
        ratio = float(self.serum_creatinine_mg_dl) / kappa
        return (
            142
            * (min(ratio, 1.0) ** alpha)
            * (max(ratio, 1.0) ** -1.200)
            * (0.9938 ** age)
            * (1.012 if is_female else 1.0)
        )

    def clean(self):
        super().clean()
        self._validate_value_matches_status(self.serum_creatinine_mg_dl)


class DrugLevel(ExactlyOneParentMixin, VerificationMixin):
    """One immunosuppressant trough result, stored LONG — one row per result so a
    patient's repeating troughs form an ordered series (Meta.ordering by drawn_date).
    Standalone: no FK to any prescription/medication model (slice 08 is OUT) so the
    real drug-exposure variable is analyzable on its own grain.

    Attaches to EXACTLY ONE parent (recipient visit XOR donor), enforced twice."""

    recipient_visit = models.ForeignKey(
        RecipientVisit,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="drug_levels",
    )
    donor = models.ForeignKey(
        Donor,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="drug_levels",
    )
    analyte = models.CharField(max_length=16, choices=DRUG_ANALYTE_CHOICES)
    value = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Trough concentration, ng/mL. Null only when result_status='missing'.",
    )
    result_status = _result_status_field()
    drawn_date = models.DateField()
    history = HistoricalRecords()

    class Meta:
        # Chronological so a patient's troughs read as an ordered series.
        ordering = ["drawn_date", "pk"]
        constraints = [
            models.CheckConstraint(
                name="druglevel_exactly_one_parent",
                condition=(
                    models.Q(recipient_visit__isnull=False, donor__isnull=True)
                    | models.Q(recipient_visit__isnull=True, donor__isnull=False)
                ),
            ),
            _status_matches_value_constraint("druglevel_value_matches_result_status"),
            *VerificationMixin.verification_constraints("druglevel_verification"),
        ]

    def clean(self):
        super().clean()
        self._validate_value_matches_status(self.value)


class OtherCondition(models.Model):
    """Long companion: one row per non-pre-specified condition on a recipient.

    Long, not wide — no column-per-possibility on Recipient. `present` is a
    three-state nullable bool (True / False / Unknown)."""

    recipient = models.ForeignKey(
        Recipient, on_delete=models.CASCADE, related_name="other_conditions"
    )
    condition = models.CharField(max_length=120)
    present = models.BooleanField(null=True, blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.recipient_id}: {self.condition}"


class MedicationCourse(models.Model):
    """One drug course on a recipient — structured numeric dose (dose_amount +
    dose_unit + frequency, never free text) so a mandated prophylaxis can never
    masquerade as a clinical response. course_type splits prophylaxis (all-40
    ~2-month valganciclovir: completed-per-protocol flag, early-discontinuation
    reason) from treatment escalation (CMV+ subset: agent, derived duration,
    dose-reduction count + reason). IS changes carry a directional typology
    (reduction vs intensification) with an optional CMV-management-intent tag so
    bidirectionality is visible. duration_days is DERIVED (derive-don't-store)."""

    recipient = models.ForeignKey(
        Recipient, on_delete=models.CASCADE, related_name="medication_courses"
    )
    drug_class = models.CharField(max_length=18, choices=DRUG_CLASS_CHOICES)
    agent = models.CharField(max_length=64, help_text="Drug name, e.g. valganciclovir, tacrolimus.")
    dose_amount = models.DecimalField(max_digits=8, decimal_places=2)
    dose_unit = models.CharField(max_length=6, choices=DOSE_UNIT_CHOICES)
    frequency = models.CharField(max_length=8, choices=FREQUENCY_CHOICES)
    course_type = models.CharField(max_length=12, choices=COURSE_TYPE_CHOICES)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True, help_text="Null = ongoing.")
    # Prophylaxis split — valid only on a prophylaxis course (clean() enforces).
    completed_per_protocol = models.BooleanField(
        null=True, blank=True, help_text="Prophylaxis only. Three-state: True/False/Unknown."
    )
    early_discontinuation_reason = models.CharField(
        max_length=12, choices=EARLY_DISCONT_REASON_CHOICES, blank=True,
        help_text="Prophylaxis only. Blank when not discontinued early.",
    )
    # Treatment-escalation split — valid only on a treatment course (clean() enforces).
    dose_reduction_count = models.PositiveIntegerField(
        null=True, blank=True, help_text="Treatment only. Number of dose reductions."
    )
    dose_reduction_reason = models.CharField(
        max_length=120, blank=True, help_text="Treatment only."
    )
    # IS directionality — valid only on an immunosuppressant course (clean() enforces).
    change_direction = models.CharField(
        max_length=15, choices=IS_CHANGE_DIRECTION_CHOICES, blank=True,
        help_text="Immunosuppressant only. Reduction vs intensification.",
    )
    cmv_management_intent = models.BooleanField(
        null=True, blank=True,
        help_text="Three-state: was this IS change made to manage CMV? True/False/Unknown.",
    )
    history = HistoricalRecords()

    class Meta:
        constraints = [
            # DB mirror of _validate_course_type_fields(): the friendly clean()
            # guard is bypassable by a bare .save()/.update(), so enforce the
            # prophylaxis/treatment field separation at the DB too.
            models.CheckConstraint(
                name="medicationcourse_no_prophylaxis_fields_on_treatment",
                condition=(
                    ~models.Q(course_type="treatment")
                    | models.Q(
                        completed_per_protocol__isnull=True,
                        early_discontinuation_reason="",
                    )
                ),
            ),
            models.CheckConstraint(
                name="medicationcourse_no_treatment_fields_on_prophylaxis",
                condition=(
                    ~models.Q(course_type="prophylaxis")
                    | models.Q(
                        dose_reduction_count__isnull=True,
                        dose_reduction_reason="",
                    )
                ),
            ),
        ]

    def __str__(self):
        return f"{self.recipient_id} {self.agent} ({self.course_type})"

    @property
    def duration_days(self):
        """Course length in days. Derived, never stored — None while ongoing."""
        if self.end_date is None:
            return None
        return (self.end_date - self.start_date).days

    def _validate_course_type_fields(self):
        """Prophylaxis-only and treatment-only fields must not cross over."""
        if self.course_type == "treatment":
            if self.completed_per_protocol is not None or self.early_discontinuation_reason:
                raise ValidationError(
                    "Prophylaxis-only fields (completed_per_protocol, "
                    "early_discontinuation_reason) must be empty on a treatment course."
                )
        if self.course_type == "prophylaxis":
            if self.dose_reduction_count is not None or self.dose_reduction_reason:
                raise ValidationError(
                    "Treatment-only fields (dose_reduction_count, dose_reduction_reason) "
                    "must be empty on a prophylaxis course."
                )

    def clean(self):
        super().clean()
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValidationError("end_date cannot precede start_date.")
        self._validate_course_type_fields()
        if self.change_direction and self.drug_class != "immunosuppressant":
            raise ValidationError(
                "change_direction applies only to an immunosuppressant course."
            )


class RejectionEpisode(VerificationMixin):
    """One allograft-rejection episode on a recipient — mirrors the CMV-episode
    shape (onset/resolved dates, type, treatment). Carries the Banff vocabulary and
    a biopsy_proven flag. Suspected-vs-biopsy-proven inclusion is deferred (PRD):
    the flag is modelled, never gated on here. As the one STORED, human-adjudicated
    episode (Banff grade/type/resolution are clinician judgements), it carries the
    four-eyes VerificationMixin for "episode adjudication" (US 68, DEC-021)."""

    recipient = models.ForeignKey(
        Recipient, on_delete=models.CASCADE, related_name="rejection_episodes"
    )
    onset_date = models.DateField()
    rejection_type = models.CharField(max_length=8, choices=REJECTION_TYPE_CHOICES)
    banff_grade = models.CharField(max_length=12, choices=BANFF_GRADE_CHOICES, blank=True)
    biopsy_proven = models.BooleanField(default=False)
    biopsy_date = models.DateField(null=True, blank=True)
    treatment = models.CharField(max_length=120, blank=True)
    resolved_date = models.DateField(null=True, blank=True, help_text="Null = unresolved.")
    history = HistoricalRecords()

    class Meta:
        constraints = VerificationMixin.verification_constraints("rejectionepisode_verification")

    def __str__(self):
        return f"{self.recipient_id} {self.rejection_type} @ {self.onset_date}"

    def clean(self):
        super().clean()
        if self.biopsy_proven and self.biopsy_date is None:
            raise ValidationError("A biopsy_proven episode must carry a biopsy_date.")
        if self.biopsy_date is not None and self.biopsy_date < self.onset_date:
            raise ValidationError("biopsy_date cannot precede onset_date.")
        if self.resolved_date is not None and self.resolved_date < self.onset_date:
            raise ValidationError("resolved_date cannot precede onset_date.")


class Hospitalization(models.Model):
    """An ALL-CAUSE admission on a recipient. CMV/rejection attribution is set BY
    HAND by a reviewing clinician — NEVER auto-inferred from date overlap (the
    guarantee is the absence of any save()/signal that populates the FKs). Both
    attribution FKs are nullable with NO exactly-one constraint (both may be null).
    cmv_attributable is a SEPARATE honest-denominator flag (US 36), independent of
    the FK. length_of_stay is DERIVED (derive-don't-store)."""

    recipient = models.ForeignKey(
        Recipient, on_delete=models.CASCADE, related_name="hospitalizations"
    )
    admit_date = models.DateField()
    discharge_date = models.DateField(null=True, blank=True, help_text="Null = still admitted.")
    reason = models.CharField(
        max_length=120, help_text="All-cause reason. Free text — never exported (leak vector)."
    )
    disposition = models.CharField(max_length=16, choices=DISPOSITION_CHOICES, blank=True)
    cmv_attribution = models.ForeignKey(
        CMVQuantitative, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="Reviewer-set link to the responsible positive draw. Never auto-inferred.",
    )
    rejection_attribution = models.ForeignKey(
        RejectionEpisode, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="Reviewer-set link to the responsible rejection episode. Never auto-inferred.",
    )
    cmv_attributable = models.BooleanField(
        default=False,
        help_text="Honest-denominator flag (US 36): reviewer judgement that the admission is "
        "CMV-attributable. Independent of cmv_attribution.",
    )
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.recipient_id} admit {self.admit_date}"

    @property
    def length_of_stay_days(self):
        """LOS in days. Derived, never stored — None while still admitted."""
        if self.discharge_date is None:
            return None
        return (self.discharge_date - self.admit_date).days

    def clean(self):
        super().clean()
        if self.discharge_date is not None and self.discharge_date < self.admit_date:
            raise ValidationError("discharge_date cannot precede admit_date.")


class PipelineRun(models.Model):
    """One genotyping pipeline run — the system-of-record for a manual
    BioEdit/BLASTn/MAFFT analysis (provenance, not orchestration). Fleshed out in
    slice 10 from the slice-09 stub. `input_manifest_sha256` is the idempotency
    key: `ingest_genotyping` reuses an existing run rather than duplicating it.
    `started_at`/`completed_at` are pipeline-process dates, NEVER subject calendar
    dates and structurally outside every export `*_COLUMNS` list."""

    reference_set = models.ForeignKey(
        "ReferenceSet",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="pipeline_runs",
        help_text="SHA-pinned GenBank reference set used for BLASTn assignment.",
    )
    started_at = models.DateField(null=True, blank=True)
    completed_at = models.DateField(null=True, blank=True)
    input_manifest_sha256 = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        help_text="SHA-256 of the input manifest — the idempotency key.",
    )
    tool_versions = models.TextField(
        blank=True, default="", help_text="Free-text tool/version provenance. Never exported."
    )
    history = HistoricalRecords()

    def __str__(self):
        return f"PipelineRun {self.pk}"


class Aliquot(models.Model):
    """One straw of post-clinical-assay residual — the canonical physical record,
    one portion per matrix per timepoint. The event-sourced ledger root: thaw and
    consumption are APPENDED (never edited), so `remaining_ul` and `thaw_count` are
    DERIVED @property by summing the event log and can never drift from the
    physical freezer or lie about history (derive-don't-store). The ledger needs
    only a volume, so the visit FK is opportunistic (nullable; slice 03)."""

    recipient_visit = models.ForeignKey(
        RecipientVisit,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="aliquots",
        help_text="Opportunistic per-timepoint anchor (slice 03). Null = unanchored straw.",
    )
    matrix = models.CharField(max_length=12, choices=MATRIX_CHOICES)
    collected_date = models.DateField()
    initial_volume_ul = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="As-banked volume, µL. The ledger ceiling."
    )
    history = HistoricalRecords()

    def __str__(self):
        return f"Aliquot {self.pk} ({self.matrix})"

    @property
    def remaining_ul(self):
        """initial_volume_ul − Σ consumption volumes. Derived, never stored, so the
        ledger cannot drift from the freezer."""
        consumed = sum(
            (e.volume_ul for e in self.consumption_events.all()), Decimal("0")
        )
        return self.initial_volume_ul - consumed

    @property
    def thaw_count(self):
        """Number of appended thaw events. Derived, never stored."""
        return self.thaw_events.count()


class ThawEvent(models.Model):
    """An append-only thaw record. A unique constraint on `aliquot` enforces
    single-use / no-refreeze at the DB level — a second thaw is rejected."""

    aliquot = models.ForeignKey(
        Aliquot, on_delete=models.CASCADE, related_name="thaw_events"
    )
    thawed_date = models.DateField()
    history = HistoricalRecords()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                name="thawevent_single_use_no_refreeze", fields=["aliquot"]
            ),
        ]

    def __str__(self):
        return f"Thaw of aliquot {self.aliquot_id}"


class ConsumptionEvent(models.Model):
    """An append-only consumption record drawing volume off an aliquot. Over-draw is
    rejected at BOTH layers: a DB CheckConstraint (volume_ul > 0) and an app-layer
    clean() guard (volume_ul must not exceed the aliquot's current remaining_ul).
    `pipeline_run` is a nullable FK closing the tube→analysis custody chain."""

    aliquot = models.ForeignKey(
        Aliquot, on_delete=models.CASCADE, related_name="consumption_events"
    )
    pipeline_run = models.ForeignKey(
        "PipelineRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="consumption_events",
        help_text="Analysis run that consumed this volume (slice 10). Null = not yet linked.",
    )
    volume_ul = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="Volume drawn, µL. Must be > 0."
    )
    consumed_date = models.DateField()
    history = HistoricalRecords()

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="consumptionevent_volume_positive", condition=models.Q(volume_ul__gt=0)
            ),
        ]

    def __str__(self):
        return f"Consumption of {self.volume_ul}µL from aliquot {self.aliquot_id}"

    def clean(self):
        super().clean()
        if self.volume_ul is not None and self.volume_ul <= 0:
            raise ValidationError("volume_ul must be greater than zero.")
        # App-layer over-consumption guard: the draw cannot exceed what remains.
        # remaining_ul sums the already-saved events, excluding this unsaved one.
        if self.volume_ul is not None and self.aliquot_id is not None:
            if self.volume_ul > self.aliquot.remaining_ul:
                raise ValidationError(
                    f"volume_ul {self.volume_ul} exceeds the aliquot's remaining "
                    f"{self.aliquot.remaining_ul}µL."
                )


class SequencingAliquot(models.Model):
    """The ONE aliquot transferred to PGC for sequencing, kept DISTINCT from the
    SPMC-held residual (its own table, OneToOne to the source `Aliquot`). Carries
    the destruction-certificate field per MOA. Saving one does not touch the source
    aliquot's ledger."""

    aliquot = models.OneToOneField(
        Aliquot, on_delete=models.CASCADE, related_name="sequencing_aliquot"
    )
    transfer_date = models.DateField()
    destruction_certificate = models.CharField(
        max_length=120,
        help_text="PGC destruction certificate ref per MOA (default per-sample). "
        "Free text — never exported (leak vector).",
    )
    history = HistoricalRecords()

    def __str__(self):
        return f"SequencingAliquot for aliquot {self.aliquot_id}"


# --- Slice 10: genotyping ingest (provenance, not orchestration) ---


class ReferenceSet(models.Model):
    """The frozen GenBank reference accession set (e.g. Ross 2020), SHA-pinned so
    BLASTn assignment is reproducible. `content_sha256` is immutable once stored —
    re-pinning the same content is idempotent; tampering changes the SHA and is
    detectable (mirror the append-only precedent at ThawEvent)."""

    name = models.CharField(max_length=120, unique=True)
    citation = models.CharField(max_length=240, blank=True, default="")
    content_sha256 = models.CharField(
        max_length=64, unique=True, help_text="SHA-256 over the frozen accession set."
    )
    pinned_at = models.DateField(null=True, blank=True)
    history = HistoricalRecords()

    IMMUTABLE_FIELDS = ("content_sha256",)
    objects = AppendOnlyQuerySet.as_manager()

    def __str__(self):
        return f"ReferenceSet {self.name}"

    def clean(self):
        super().clean()
        if self.pk is not None:
            stored = ReferenceSet.objects.get(pk=self.pk)
            if stored.content_sha256 != self.content_sha256:
                raise ValidationError("content_sha256 is immutable once pinned.")


class ReferenceAccession(models.Model):
    """One GenBank accession within a pinned reference set, mapped to its genotype."""

    reference_set = models.ForeignKey(
        ReferenceSet, on_delete=models.CASCADE, related_name="accessions"
    )
    accession = models.CharField(max_length=32)
    genotype = models.CharField(max_length=32)
    history = HistoricalRecords()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                name="referenceaccession_unique_per_set",
                fields=["reference_set", "accession"],
            ),
        ]

    def __str__(self):
        return f"{self.accession} ({self.genotype})"


class GenotypingResult(models.Model):
    """One genotyping result anchored to the source `Aliquot` — subject and
    sample-date are DERIVED through the tube (never stored on the result),
    preserving the slice-09 custody chain (derive-don't-store). The optional
    `cmv_episode_anchor` FK targets the recipient-anchored dated viral-load draw
    (DEC-019, the DEC-017 precedent) so within-patient genotype-over-time analysis
    is joinable without contradicting slice-07's derive-at-read episodes."""

    aliquot = models.ForeignKey(
        Aliquot, on_delete=models.PROTECT, related_name="genotyping_results"
    )
    pipeline_run = models.ForeignKey(
        PipelineRun, on_delete=models.PROTECT, related_name="genotyping_results"
    )
    cmv_episode_anchor = models.ForeignKey(
        CMVQuantitative,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="genotyping_results",
        help_text="Optional anchor to a dated positive QNAT draw (DEC-019).",
    )
    assay_type = models.CharField(max_length=8, choices=ASSAY_TYPE_CHOICES)
    history = HistoricalRecords()

    def __str__(self):
        return f"GenotypingResult {self.pk} ({self.assay_type})"

    @property
    def subject(self):
        """Recipient derived THROUGH the tube — never a stored column. None when
        the source aliquot has no visit anchor."""
        visit = self.aliquot.recipient_visit
        return visit.recipient if visit is not None else None

    @property
    def sample_date(self):
        """Sample date derived through the tube (the aliquot's collection date)."""
        return self.aliquot.collected_date

    @property
    def qpcr_rollup(self):
        """single / mixed / untyped rolled up from the qPCR probe readings; blank
        for a Sanger result with no qPCR detail."""
        detail = self.qpcr_details.first()
        return detail.rollup if detail is not None else ""


class GenotypeCall(VerificationMixin):
    """One allele call, stored LONG (first normal form) — a mixed infection is
    multiple rows for the same result/locus, never collapsed by a unique
    constraint. No call is finalized (`is_verified`) without a second-reviewer lock
    set by a DIFFERENT user, enforced at BOTH the app layer (clean()) and the DB
    layer (two CheckConstraints), mirroring the ConsumptionEvent dual-guard. The
    four-eyes gate is the shared VerificationMixin (US 68, DEC-022): `is_locked`/
    `reviewed_by`/`reviewed_at` became `is_verified`/`verified_by`/`verified_at`."""

    result = models.ForeignKey(
        GenotypingResult, on_delete=models.CASCADE, related_name="calls"
    )
    locus = models.CharField(max_length=16)
    allele = models.CharField(max_length=32)
    sanger_call = models.CharField(
        max_length=1, choices=SANGER_CALL_CHOICES, null=True, blank=True,
        help_text="Sanger R/F/N taxonomy; null for a qPCR-derived call.",
    )
    history = HistoricalRecords()

    class Meta:
        constraints = VerificationMixin.verification_constraints("genotypecall_verification")

    def __str__(self):
        return f"{self.locus}={self.allele}"

    def clean(self):
        super().clean()  # the mixin's four-eyes gate runs first
        # Once verified, the call is frozen: its allele content cannot be edited
        # (SangerDetail append-only precedent). Freeze keys off the STORED lock so
        # an unlock-and-edit cannot slip a change through.
        if self.pk is not None:
            stored = GenotypeCall.objects.get(pk=self.pk)
            if stored.is_verified and (
                stored.locus != self.locus
                or stored.allele != self.allele
                or stored.sanger_call != self.sanger_call
            ):
                raise ValidationError(
                    "A verified call is frozen; locus/allele/sanger_call cannot be changed."
                )


class SangerDetail(models.Model):
    """Append-only raw `.ab1` reference (unique by content SHA-256, never
    overwritten) plus the reviewed consensus attributed to its editor. The raw
    reference is write-once: a unique constraint blocks a second row for the same
    SHA, and clean() refuses to mutate an existing raw reference (ThawEvent
    single-use precedent)."""

    result = models.ForeignKey(
        GenotypingResult, on_delete=models.CASCADE, related_name="sanger_details"
    )
    raw_ab1_sha256 = models.CharField(max_length=64, unique=True)
    raw_ab1_path = models.CharField(max_length=255)
    consensus_sequence = models.TextField(blank=True, default="")
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sanger_consensus_edits",
        help_text="Editor of the reviewed consensus (attribution). Never exported.",
    )
    history = HistoricalRecords()

    IMMUTABLE_FIELDS = ("raw_ab1_sha256", "raw_ab1_path")
    objects = AppendOnlyQuerySet.as_manager()

    def __str__(self):
        return f"SangerDetail {self.raw_ab1_sha256[:8]}"

    def clean(self):
        super().clean()
        if self.pk is None:
            return
        stored = SangerDetail.objects.get(pk=self.pk)
        if (
            stored.raw_ab1_sha256 != self.raw_ab1_sha256
            or stored.raw_ab1_path != self.raw_ab1_path
        ):
            raise ValidationError("Raw .ab1 reference is append-only; it cannot be overwritten.")


class QpcrDetail(models.Model):
    """A qPCR result's per-probe readings (a repeating group). `rollup` is DERIVED
    from the probe readings — single (one P), mixed (≥2 P), untyped (no P) — never
    a stored column."""

    result = models.ForeignKey(
        GenotypingResult, on_delete=models.CASCADE, related_name="qpcr_details"
    )
    history = HistoricalRecords()

    def __str__(self):
        return f"QpcrDetail {self.pk}"

    @property
    def rollup(self):
        positives = sum(1 for r in self.probe_readings.all() if r.call == "P")
        if positives >= 2:
            return "mixed"
        if positives == 1:
            return "single"
        return "untyped"


class QpcrProbeReading(models.Model):
    """One per-probe P/N/I reading. The second-reviewer gate is scoped to
    indeterminate (`I`) readings ONLY — clean P/N calls are not slowed. clean()
    requires a different reviewer + timestamp when `call == 'I'`."""

    qpcr_detail = models.ForeignKey(
        QpcrDetail, on_delete=models.CASCADE, related_name="probe_readings"
    )
    probe = models.CharField(max_length=16)
    call = models.CharField(max_length=1, choices=QPCR_PROBE_CHOICES)
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="qpcr_readings_entered",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="qpcr_readings_reviewed",
    )
    reviewed_at = models.DateField(null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        # DB-level second-reviewer gate, mirroring GenotypeCall's lock so a bare
        # .save() (not just full_clean/admin/ingest) cannot bypass it. Both fire
        # only on an indeterminate ('I') reading; non-'I' rows are unconstrained.
        constraints = [
            models.CheckConstraint(
                name="qpcrprobereading_indeterminate_requires_reviewer",
                condition=(
                    ~models.Q(call="I")
                    | models.Q(reviewed_by__isnull=False, reviewed_at__isnull=False)
                ),
            ),
            models.CheckConstraint(
                name="qpcrprobereading_reviewer_differs_when_indeterminate",
                condition=(
                    ~models.Q(call="I")
                    | ~models.Q(reviewed_by=models.F("entered_by"))
                ),
            ),
        ]

    def __str__(self):
        return f"{self.probe}={self.call}"

    def clean(self):
        super().clean()
        if self.call != "I":
            return
        if self.reviewed_by_id is None or self.reviewed_at is None:
            raise ValidationError("An indeterminate (I) reading requires a second reviewer.")
        if self.entered_by_id is not None and self.entered_by_id == self.reviewed_by_id:
            raise ValidationError("The second reviewer must differ from the editor.")


# --- Slice 11: source attribution & genotype concordance (Obj 5) ---


class ConcordancePair(models.Model):
    """One reviewer-adjudicated genotype-concordance comparison for a recipient:
    the recipient's `recipient_result` against an optional `comparator_result`
    (a second GenotypingResult — a donor genotype path may land later, DEC-024).

    `suggested_concordance_call` and `co_resolved_count` are DERIVED at read from
    the two results' GenotypeCalls (the pure grader, derive-don't-store). The
    reviewer's own `concordance_call` is a SEPARATE stored field that is never
    auto-overwritten — false precision is recordable as `indeterminate`.
    `reviewed_by`/`reviewed_at` are staff attribution and are NEVER exported."""

    recipient = models.ForeignKey(
        Recipient, on_delete=models.PROTECT, related_name="concordance_pairs"
    )
    recipient_result = models.ForeignKey(
        GenotypingResult, on_delete=models.PROTECT, related_name="+"
    )
    comparator_result = models.ForeignKey(
        GenotypingResult,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Optional second strain to compare against. Absent -> < 2 co-resolved "
        "loci -> indeterminate (the honest grading).",
    )
    concordance_call = models.CharField(
        max_length=16,
        choices=CONCORDANCE_CALL_CHOICES,
        blank=True,
        default="",
        help_text="Reviewer-set tier. Never auto-overwritten by the suggestion; "
        "false precision is recorded as 'indeterminate'.",
    )
    superinfection_status = models.CharField(
        max_length=12,
        choices=SUPERINFECTION_STATUS_CHOICES,
        default="none",
        help_text="Mixed-infection donor-derived superinfection flag. Only 'confirmed' "
        "upgrades the recipient's source_label to donor_derived; 'candidate' does not.",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="concordance_pairs_reviewed",
    )
    reviewed_at = models.DateField(null=True, blank=True)
    history = HistoricalRecords()

    class Meta:
        constraints = [
            # A pair is never a result against itself (mirror the GenotypeCall
            # dual-guard idiom; NULL comparator passes the CHECK harmlessly).
            models.CheckConstraint(
                name="concordancepair_not_self_comparison",
                condition=~models.Q(comparator_result=models.F("recipient_result")),
            ),
        ]

    def __str__(self):
        return f"ConcordancePair {self.pk} ({self.recipient_id})"

    def _calls_by_locus(self, result):
        """{locus: {alleles: set, resolved: bool}} for a result. A locus is resolved
        when at least one of its calls is not a Sanger failure/no-amplicon (a qPCR
        call carries sanger_call=None and counts as resolved)."""
        out = {}
        if result is None:
            return out
        for call in result.calls.all():
            entry = out.setdefault(call.locus, {"alleles": set(), "resolved": False})
            entry["alleles"].add(call.allele)
            if call.sanger_call in (None, "R"):
                entry["resolved"] = True
        return out

    def locus_comparisons(self):
        """Per-locus comparison dicts over the union of loci in either member,
        in the pure grader's shape."""
        a = self._calls_by_locus(self.recipient_result)
        b = self._calls_by_locus(self.comparator_result if self.comparator_result_id else None)
        empty = {"alleles": set(), "resolved": False}
        comparisons = []
        for locus in set(a) | set(b):
            ca = a.get(locus, empty)
            cb = b.get(locus, empty)
            comparisons.append({
                "locus": locus,
                "allele_a_set": ca["alleles"],
                "allele_b_set": cb["alleles"],
                "resolved_a": ca["resolved"],
                "resolved_b": cb["resolved"],
            })
        return comparisons

    @property
    def comparator_subject(self):
        """The comparator result's recipient (through the tube), else None."""
        return self.comparator_result.subject if self.comparator_result_id else None

    @property
    def suggested_concordance_call(self):
        """Graded tier the stored GenotypeCalls imply — a SUGGESTION the reviewer
        may override. Derived, never stored."""
        return grade_concordance(self.locus_comparisons())

    @property
    def co_resolved_count(self):
        """Number of co-resolved strain-identity loci (resistance excluded)."""
        return sum(
            1
            for c in self.locus_comparisons()
            if c["resolved_a"] and c["resolved_b"] and counted_for_strain_identity(c["locus"])
        )

    def clean(self):
        super().clean()
        if (
            self.recipient_result_id is not None
            and self.recipient_result.subject != self.recipient
        ):
            raise ValidationError("recipient_result must belong to this recipient.")
        if (
            self.comparator_result_id is not None
            and self.comparator_result_id == self.recipient_result_id
        ):
            raise ValidationError("comparator_result cannot be the recipient_result itself.")
        if self.superinfection_status in ("candidate", "confirmed") and self.comparator_result_id is None:
            raise ValidationError(
                "A candidate/confirmed superinfection requires a comparator_result "
                "(no donor-derived superinfection without a comparator strain)."
            )


# --- Slice 12: resistance surveillance (UL97 / UL54, Q11.7) ---


class ResistanceCall(models.Model):
    """One UL97/UL54 antiviral-resistance surveillance call, kept DISTINCT from
    strain-identity genotyping so drug attribution is never pooled away. It rides
    the SAME pipeline-run/result chain (`result` FK); subject, visit, and
    sample-date are DERIVED through the tube (never stored), the slice-10
    GenotypingResult precedent. The established-present bool, the active-failure
    flag, and the tiered return-of-results flag are all derived @property
    (derive-don't-store) so they can never drift from the three-tier variant data.
    `qnat_iu_ml` is the QNAT at the call — a Decimal value, never a calendar date.

    The locked two-locus list is enforced TWICE: a DB CheckConstraint plus the
    friendly clean() mirror (the project enforce-twice idiom)."""

    result = models.ForeignKey(
        GenotypingResult, on_delete=models.PROTECT, related_name="resistance_calls"
    )
    locus = models.CharField(max_length=8, choices=RESISTANCE_LOCUS_CHOICES)
    status = models.CharField(
        max_length=1,
        choices=SANGER_CALL_CHOICES,
        help_text="R/F/N — the same Sanger taxonomy as a GenotypeCall.",
    )
    qnat_iu_ml = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="COBAS 5000 IU/mL viral load AT the call (amplification-floor context). "
        "A value, never a date; null when no QNAT was recorded at the call.",
    )
    history = HistoricalRecords()

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="resistancecall_locus_is_ul97_or_ul54",
                condition=models.Q(locus__in=RESISTANCE_LOCI),
            ),
        ]

    def __str__(self):
        return f"ResistanceCall {self.pk} ({self.locus} {self.status})"

    def clean(self):
        super().clean()
        if self.locus not in RESISTANCE_LOCI:
            raise ValidationError(f"locus must be one of {RESISTANCE_LOCI}.")

    @property
    def subject(self):
        """Recipient derived THROUGH the tube — never a stored column. None when
        the source aliquot has no visit anchor."""
        return self.result.subject

    @property
    def visit(self):
        """Recipient visit derived through the tube; None when unanchored."""
        return self.result.aliquot.recipient_visit

    @property
    def sample_date(self):
        """Sample date derived through the tube (the aliquot's collection date)."""
        return self.result.sample_date

    @property
    def established_resistance_present(self):
        """Derived, never stored: any variant on this call graded `established`."""
        return any(v.tier == "established" for v in self.variants.all())

    @property
    def has_active_virological_failure(self):
        """Viremic at the call — QNAT at/above the assay LoQ (the SAME positivity
        bar episodes/attribution use). Derived, never stored."""
        return is_active_virological_failure(self.qnat_iu_ml)

    @property
    def return_of_results_flag(self):
        """The tiered duty-to-disclose flag — fires on EXACTLY the
        established-resistance ∩ active-virological-failure intersection."""
        return return_of_results(self.established_resistance_present, self.qnat_iu_ml)


class ResistanceVariant(models.Model):
    """One graded resistance variant on a `ResistanceCall`, stored LONG (1NF) — two
    variants on one call are two rows, never collapsed (the GenotypeCall
    precedent). `tier` is the curated three-tier interpretation."""

    resistance_call = models.ForeignKey(
        ResistanceCall, on_delete=models.CASCADE, related_name="variants"
    )
    variant = models.CharField(
        max_length=32, help_text="Variant/mutation code, e.g. C592G, M460V."
    )
    tier = models.CharField(max_length=12, choices=RESISTANCE_TIER_CHOICES)
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.variant} ({self.tier})"


class ReleaseEvent(models.Model):
    """One logged safety release-event for a viral-load draw (Slice 14). The
    timeliness flag on `CMVQuantitative` reads these; the recipient/kt anchor is
    DERIVED THROUGH THE TUBE (quantitative.recipient_visit.recipient), never stored.
    A release cannot predate its draw."""

    quantitative = models.ForeignKey(
        CMVQuantitative, on_delete=models.CASCADE, related_name="release_events"
    )
    released_date = models.DateField()
    history = HistoricalRecords()

    def __str__(self):
        return f"ReleaseEvent {self.pk} (qnat {self.quantitative_id})"

    def clean(self):
        super().clean()
        if self.released_date < self.quantitative.drawn_date:
            raise ValidationError("released_date cannot predate the draw's drawn_date.")

    @property
    def recipient(self):
        """Recipient derived through the tube; None for a donor-attached draw."""
        visit = self.quantitative.recipient_visit
        return visit.recipient if visit is not None else None


class ProtocolDeviation(models.Model):
    """A missed/late safety release recorded as a protocol deviation, and —
    additionally, dual-track — as a research-related SAE WHEN it caused harm
    (Slice 14). One lightweight model, two separately countable booleans (not two
    linked models); clean() enforces SAE ⇒ harm. Recipient/kt anchor derived
    through the tube, never stored."""

    quantitative = models.ForeignKey(
        CMVQuantitative, on_delete=models.CASCADE, related_name="protocol_deviations"
    )
    deviation_type = models.CharField(max_length=16, choices=DEVIATION_TYPE_CHOICES)
    caused_harm = models.BooleanField(default=False)
    is_research_related_sae = models.BooleanField(default=False)
    recorded_date = models.DateField(null=True, blank=True)
    history = HistoricalRecords()

    def __str__(self):
        return f"ProtocolDeviation {self.pk} ({self.deviation_type})"

    def clean(self):
        super().clean()
        if self.is_research_related_sae and not self.caused_harm:
            raise ValidationError(
                "A research-related SAE requires caused_harm=True (an SAE is recorded "
                "only when the deviation caused harm)."
            )

    @property
    def recipient(self):
        """Recipient derived through the tube; None for a donor-attached draw."""
        visit = self.quantitative.recipient_visit
        return visit.recipient if visit is not None else None
