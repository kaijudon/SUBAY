"""RENOVA registry models — Slice 0 walking skeleton.

The abstract BaseSubject shares identity columns into concrete Recipient/Donor
without emitting its own table. Derived clinical values (age, risk_stratum,
is_positive) are @property and never stored, so a stored fact and its computed
value can never silently disagree.
"""
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords

from .validators import subject_id_validator

SEX_CHOICES = [("M", "Male"), ("F", "Female")]
SEROSTATUS_CHOICES = [("POS", "Positive"), ("NEG", "Negative")]


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


class Donor(BaseSubject):
    """A living donor — thin, one draw."""

    history = HistoricalRecords()


class RecipientVisit(models.Model):
    recipient = models.ForeignKey(Recipient, on_delete=models.CASCADE, related_name="visits")
    visit_date = models.DateField()
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.recipient_id} @ {self.visit_date}"


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
