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
VISIT_SHIFT_CAP_DAYS = 3


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


class CMVSerology(models.Model):
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
    value = models.DecimalField(max_digits=8, decimal_places=2, help_text="Snibe Maglumi 600 AU/mL.")
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
        ]

    @property
    def is_positive(self):
        if self.value is None:
            return None
        return self.value >= self.POSITIVE_THRESHOLD

    def clean(self):
        has_visit = self.recipient_visit_id is not None
        has_donor = self.donor_id is not None
        if has_visit == has_donor:
            raise ValidationError(
                "A CMVSerology must attach to exactly one of recipient_visit or donor "
                "(not both, not neither)."
            )


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
