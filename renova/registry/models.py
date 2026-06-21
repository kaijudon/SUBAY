"""RENOVA registry models — Slice 0 walking skeleton.

The abstract BaseSubject shares identity columns into concrete Recipient/Donor
without emitting its own table. Derived clinical values (age, risk_stratum,
is_positive) are @property and never stored, so a stored fact and its computed
value can never silently disagree.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords

from .episodes import (
    SEVERITY_TIERS,
    EpisodePoint,
    derive_episodes,
    summarize_episodes,
)
from .scheduling import TIMEPOINT_OFFSETS, ClosureDayLike, first_operating_day
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


DRUG_ANALYTE_CHOICES = [("tacrolimus", "Tacrolimus"), ("everolimus", "Everolimus")]
# Clinical Kotton-2018 severity, sourced from the pure deriver so the stored
# choices can never drift from the tiers the episode logic ranks.
SEVERITY_TIER_CHOICES = [(t, t.capitalize()) for t in SEVERITY_TIERS]
VISIT_SHIFT_CAP_DAYS = 3


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
        """R+/R- computed ONCE from the pre_kt visit's IgG serology (single
        2.0 AU/mL cutoff). The canonical pre-KT serostatus both Obj 4a
        stratification and Obj 5 attribution consume — derived, never stored, so
        the two objectives can never read disagreeing values. None when there is
        no pre_kt visit or its IgG result is missing."""
        visit = self.visits.filter(timepoint_label="pre_kt").first()
        if visit is None:
            return None
        s = visit.serologies.first()
        if s is None or s.is_positive is None:
            return None
        return "POS" if s.is_positive else "NEG"

    @property
    def has_donor_serostatus_mismatch(self):
        """Flag (never overwrite) a clash between the recorded donor serostatus
        and the paired donor's own serology. Surfaces for hand reconciliation;
        both stored facts stay intact. False when either side is missing."""
        if self.donor_id is None:
            return False
        donor_status = self.donor.baseline_serostatus
        if not self.donor_serostatus or not donor_status:
            return False
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
        """POS/NEG from the donor's single serology (2.0 AU/mL threshold), else
        None. Derived — never stored, so it can't disagree with the lab value."""
        s = self.serologies.first()
        if s is None or s.is_positive is None:
            return None
        return "POS" if s.is_positive else "NEG"


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


class CMVSerology(ExactlyOneParentMixin):
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

    def clean(self):
        super().clean()
        self._validate_value_matches_status(self.value)
        if self.igm_status == "reported" and self.igm_value is None:
            raise ValidationError("A reported IgM result must carry a value.")
        if self.igm_status == "missing" and self.igm_value is not None:
            raise ValidationError("A missing IgM observation must not carry a value.")


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


class DrugLevel(ExactlyOneParentMixin):
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
