"""Slice 08 — RejectionEpisode: Banff vocabulary + biopsy-proven flag.

Mirrors the CMV-episode shape (onset/resolved dates, type, treatment). A
biopsy_proven episode must carry its biopsy_date; biopsy/resolved dates can never
precede onset.
"""
from datetime import date

import pytest
from django.core.exceptions import ValidationError

from subay.registry.models import RejectionEpisode, Recipient


@pytest.fixture
def recipient(db):
    return Recipient.objects.create(
        subject_id="SCMVR01", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )


# AC4 — Banff vocabulary + biopsy_proven flag with biopsy_date


def test_rejection_type_choices():
    field = RejectionEpisode._meta.get_field("rejection_type")
    assert {c[0] for c in field.choices} == {"tcmr", "amr", "mixed"}


def test_banff_grade_is_choices_field():
    field = RejectionEpisode._meta.get_field("banff_grade")
    assert field.choices  # a controlled vocabulary, not free text
    values = {c[0] for c in field.choices}
    assert "ia" in values and "amr_active" in values


def test_biopsy_proven_round_trip(recipient):
    e = RejectionEpisode(
        recipient=recipient, onset_date=date(2025, 3, 1), rejection_type="tcmr",
        banff_grade="ia", biopsy_proven=True, biopsy_date=date(2025, 3, 2),
    )
    e.full_clean()
    e.save()
    assert RejectionEpisode.objects.get().biopsy_proven is True


def test_biopsy_proven_without_biopsy_date_rejected(recipient):
    e = RejectionEpisode(
        recipient=recipient, onset_date=date(2025, 3, 1), rejection_type="tcmr",
        biopsy_proven=True, biopsy_date=None,
    )
    with pytest.raises(ValidationError):
        e.clean()


def test_clinical_suspected_episode_needs_no_biopsy_date(recipient):
    """biopsy_proven=False (clinically suspected) is allowed without a biopsy_date —
    inclusion is deferred to a later slice; the flag is modelled, not gated on."""
    e = RejectionEpisode(
        recipient=recipient, onset_date=date(2025, 3, 1), rejection_type="amr",
        biopsy_proven=False,
    )
    e.full_clean()
    e.save()
    assert RejectionEpisode.objects.count() == 1


def test_biopsy_date_before_onset_rejected(recipient):
    e = RejectionEpisode(
        recipient=recipient, onset_date=date(2025, 3, 1), rejection_type="tcmr",
        biopsy_proven=True, biopsy_date=date(2025, 2, 28),
    )
    with pytest.raises(ValidationError):
        e.clean()


def test_resolved_before_onset_rejected(recipient):
    e = RejectionEpisode(
        recipient=recipient, onset_date=date(2025, 3, 1), rejection_type="tcmr",
        resolved_date=date(2025, 2, 1),
    )
    with pytest.raises(ValidationError):
        e.clean()


def test_resolved_after_onset_ok(recipient):
    e = RejectionEpisode(
        recipient=recipient, onset_date=date(2025, 3, 1), rejection_type="tcmr",
        treatment="steroid pulse", resolved_date=date(2025, 3, 20),
    )
    e.full_clean()
    e.save()
    assert RejectionEpisode.objects.count() == 1


def test_history_tracked(recipient):
    e = RejectionEpisode.objects.create(
        recipient=recipient, onset_date=date(2025, 3, 1), rejection_type="tcmr"
    )
    assert e.history.count() == 1
