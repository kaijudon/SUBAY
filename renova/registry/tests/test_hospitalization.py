"""Slice 08 — Hospitalization: ALL-CAUSE with reviewer-set nullable attribution.

The load-bearing slice. Attribution (CMV / rejection) is set BY HAND by a
reviewing clinician — NEVER auto-inferred from date overlap. Both attribution FKs
are nullable with NO exactly-one constraint (both may be null). length_of_stay is
derived (derive-don't-store), never a column. The honest-denominator
cmv_attributable flag is independent of the FK.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from renova.registry.models import (
    CMVQuantitative,
    Hospitalization,
    Recipient,
    RecipientVisit,
    RejectionEpisode,
)


@pytest.fixture
def recipient(db):
    return Recipient.objects.create(
        subject_id="SCMVR01", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )


# AC5 — all-cause; both attribution FKs nullable, no exactly-one


def test_both_attribution_fks_nullable():
    cmv = Hospitalization._meta.get_field("cmv_attribution")
    rej = Hospitalization._meta.get_field("rejection_attribution")
    assert cmv.null and cmv.blank
    assert rej.null and rej.blank


def test_no_exactly_one_constraint_on_attribution_fks():
    """The card forbids an exactly-one constraint — both FKs may be null."""
    for c in Hospitalization._meta.constraints:
        names = getattr(getattr(c, "condition", None), "children", [])
        # No constraint should reference both attribution FKs as a XOR rule.
        rendered = str(getattr(c, "condition", ""))
        assert not ("cmv_attribution" in rendered and "rejection_attribution" in rendered)


def test_all_cause_row_with_both_attributions_null_saves(recipient):
    h = Hospitalization(
        recipient=recipient, admit_date=date(2025, 4, 1), discharge_date=date(2025, 4, 5),
        reason="urosepsis", disposition="discharged_home",
    )
    h.full_clean()
    h.save()
    saved = Hospitalization.objects.get()
    assert saved.cmv_attribution_id is None
    assert saved.rejection_attribution_id is None


def test_attribution_not_auto_inferred_from_date_overlap(recipient):
    """LOAD-BEARING: a positive CMV draw inside the admit/discharge window must NOT
    populate the attribution FK. The guarantee is the absence of inference code."""
    v = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_7", actual_visit_date=date(2025, 4, 3)
    )
    CMVQuantitative.objects.create(  # positive draw falls INSIDE the admission window
        recipient_visit=v, value=Decimal("1500"), drawn_date=date(2025, 4, 3),
    )
    h = Hospitalization(
        recipient=recipient, admit_date=date(2025, 4, 1), discharge_date=date(2025, 4, 5),
        reason="fever",
    )
    h.full_clean()
    h.save()
    h.refresh_from_db()
    assert h.cmv_attribution_id is None  # NOT auto-inferred from overlap
    assert h.rejection_attribution_id is None
    assert h.cmv_attributable is False  # honest-denominator flag is hand-set, defaults False


def test_reviewer_can_hand_set_attribution(recipient):
    v = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_7", actual_visit_date=date(2025, 4, 3)
    )
    q = CMVQuantitative.objects.create(
        recipient_visit=v, value=Decimal("1500"), drawn_date=date(2025, 4, 3),
    )
    rej = RejectionEpisode.objects.create(
        recipient=recipient, onset_date=date(2025, 4, 1), rejection_type="tcmr"
    )
    h = Hospitalization.objects.create(
        recipient=recipient, admit_date=date(2025, 4, 1), discharge_date=date(2025, 4, 5),
        reason="fever", cmv_attribution=q, rejection_attribution=rej, cmv_attributable=True,
    )
    h.refresh_from_db()
    assert h.cmv_attribution_id == q.id
    assert h.rejection_attribution_id == rej.id
    assert h.cmv_attributable is True


def test_attribution_set_null_on_draw_delete(recipient):
    """Deleting an attributed draw must NOT cascade-delete the all-cause admission."""
    v = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_7", actual_visit_date=date(2025, 4, 3)
    )
    q = CMVQuantitative.objects.create(
        recipient_visit=v, value=Decimal("1500"), drawn_date=date(2025, 4, 3),
    )
    h = Hospitalization.objects.create(
        recipient=recipient, admit_date=date(2025, 4, 1), reason="fever", cmv_attribution=q,
    )
    q.delete()
    h.refresh_from_db()
    assert Hospitalization.objects.filter(pk=h.pk).exists()
    assert h.cmv_attribution_id is None


def test_length_of_stay_derived(recipient):
    h = Hospitalization(
        recipient=recipient, admit_date=date(2025, 4, 1), discharge_date=date(2025, 4, 6),
        reason="fever",
    )
    assert h.length_of_stay_days == 5


def test_length_of_stay_none_when_open(recipient):
    h = Hospitalization(recipient=recipient, admit_date=date(2025, 4, 1), reason="fever")
    assert h.length_of_stay_days is None


def test_discharge_before_admit_rejected(recipient):
    h = Hospitalization(
        recipient=recipient, admit_date=date(2025, 4, 5), discharge_date=date(2025, 4, 1),
        reason="fever",
    )
    with pytest.raises(ValidationError):
        h.clean()


def test_history_tracked(recipient):
    h = Hospitalization.objects.create(
        recipient=recipient, admit_date=date(2025, 4, 1), reason="fever"
    )
    assert h.history.count() == 1
