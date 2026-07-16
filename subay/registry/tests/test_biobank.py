"""Slice 09 — Biobank ledger: tube → thaw → consumption, append-only.

The deep module. `remaining_ul` and `thaw_count` are DERIVED @property by summing
the event log — never a stored/mutable column — so the ledger cannot drift from
the physical freezer and cannot lie about history. Over-consumption is rejected at
BOTH the DB layer (CHECK volume_ul > 0) and the app layer (clean() guard vs
current remaining). A second thaw breaching single-use / no-refreeze is rejected
at the DB level (unique constraint). `SequencingAliquot` tracks the one
PGC-transferred straw with a destruction-certificate, distinct from SPMC residual.
`ConsumptionEvent.pipeline_run` is a nullable FK closing tube→analysis custody.

The ledger logic needs only an Aliquot with a volume, so it is built and tested
independently of the visit spine; the per-timepoint FK attaches opportunistically.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction

from subay.registry.models import (
    Aliquot,
    ConsumptionEvent,
    PipelineRun,
    Recipient,
    RecipientVisit,
    SequencingAliquot,
    ThawEvent,
)


@pytest.fixture
def aliquot(db):
    """A bare aliquot with a volume — no visit anchor needed for the ledger."""
    return Aliquot.objects.create(
        matrix="plasma", collected_date=date(2025, 1, 15),
        initial_volume_ul=Decimal("1000"),
    )


@pytest.fixture
def anchored_aliquot(db):
    """An aliquot attached to a recipient visit (the opportunistic FK path)."""
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 15)
    )
    return Aliquot.objects.create(
        recipient_visit=v, matrix="plasma", collected_date=date(2025, 1, 15),
        initial_volume_ul=Decimal("1000"),
    )


# --- AC1: remaining_ul / thaw_count are DERIVED, never stored ---


def test_remaining_ul_full_when_no_consumption(aliquot):
    assert aliquot.remaining_ul == Decimal("1000")


def test_remaining_ul_sums_appended_consumption(aliquot):
    ConsumptionEvent.objects.create(
        aliquot=aliquot, volume_ul=Decimal("200"), consumed_date=date(2025, 2, 1)
    )
    ConsumptionEvent.objects.create(
        aliquot=aliquot, volume_ul=Decimal("150"), consumed_date=date(2025, 2, 2)
    )
    assert aliquot.remaining_ul == Decimal("650")  # 1000 - (200 + 150)


def test_thaw_count_counts_appended_thaws(aliquot):
    assert aliquot.thaw_count == 0
    ThawEvent.objects.create(aliquot=aliquot, thawed_date=date(2025, 2, 1))
    assert aliquot.thaw_count == 1


def test_no_stored_remaining_or_thaw_count_column():
    field_names = {f.name for f in Aliquot._meta.get_fields()}
    assert "remaining_ul" not in field_names
    assert "thaw_count" not in field_names
    assert "remaining_volume" not in field_names
    assert isinstance(Aliquot.remaining_ul, property)
    assert isinstance(Aliquot.thaw_count, property)


def test_remaining_ul_recomputes_after_adding_event(aliquot):
    """Derived value changes purely by appending — never by writing a column."""
    assert aliquot.remaining_ul == Decimal("1000")
    ConsumptionEvent.objects.create(
        aliquot=aliquot, volume_ul=Decimal("400"), consumed_date=date(2025, 2, 1)
    )
    assert aliquot.remaining_ul == Decimal("600")


# --- AC3: over-consumption rejected at BOTH the DB and app layer ---


def test_consumption_nonpositive_volume_rejected_by_db(aliquot):
    """DB layer: CheckConstraint volume_ul > 0."""
    ce = ConsumptionEvent(aliquot=aliquot, volume_ul=Decimal("0"), consumed_date=date(2025, 2, 1))
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ce.save()


def test_over_consumption_rejected_by_app_guard(aliquot):
    """App layer: clean() rejects a consumption exceeding current remaining_ul."""
    ConsumptionEvent.objects.create(
        aliquot=aliquot, volume_ul=Decimal("800"), consumed_date=date(2025, 2, 1)
    )
    over = ConsumptionEvent(
        aliquot=aliquot, volume_ul=Decimal("300"), consumed_date=date(2025, 2, 2)
    )  # only 200 µL remain
    with pytest.raises(ValidationError):
        over.clean()


def test_consumption_up_to_remaining_is_allowed(aliquot):
    exact = ConsumptionEvent(
        aliquot=aliquot, volume_ul=Decimal("1000"), consumed_date=date(2025, 2, 1)
    )
    exact.full_clean()  # draining the straw exactly is legal
    exact.save()
    assert aliquot.remaining_ul == Decimal("0")


# --- AC4: single-use / no-refreeze enforced at the DB level ---


def test_second_thaw_rejected_by_db(aliquot):
    ThawEvent.objects.create(aliquot=aliquot, thawed_date=date(2025, 2, 1))
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ThawEvent.objects.create(aliquot=aliquot, thawed_date=date(2025, 2, 2))


# --- AC5: SequencingAliquot tracks the PGC transfer, distinct from residual ---


def test_sequencing_aliquot_has_destruction_certificate(anchored_aliquot):
    sa = SequencingAliquot.objects.create(
        aliquot=anchored_aliquot, transfer_date=date(2025, 3, 1),
        destruction_certificate="MOA-2025-0042",
    )
    assert sa.destruction_certificate == "MOA-2025-0042"
    assert sa.aliquot_id == anchored_aliquot.pk


def test_sequencing_aliquot_is_distinct_and_does_not_alter_ledger(aliquot):
    """Saving a SequencingAliquot is its own record; the source ledger is untouched."""
    before = aliquot.remaining_ul
    SequencingAliquot.objects.create(
        aliquot=aliquot, transfer_date=date(2025, 3, 1), destruction_certificate="MOA-1"
    )
    aliquot.refresh_from_db()
    assert aliquot.remaining_ul == before  # residual ledger unchanged
    assert SequencingAliquot._meta.db_table != Aliquot._meta.db_table


def test_sequencing_aliquot_is_one_to_one(aliquot):
    field = SequencingAliquot._meta.get_field("aliquot")
    assert field.one_to_one


# --- AC6: ConsumptionEvent.pipeline_run nullable FK closing custody ---


def test_pipeline_run_fk_is_nullable_set_null(aliquot):
    f = ConsumptionEvent._meta.get_field("pipeline_run")
    assert f.null and f.blank
    assert f.remote_field.on_delete is models.SET_NULL
    assert f.related_model is PipelineRun


def test_consumption_saves_with_null_pipeline_run(aliquot):
    ce = ConsumptionEvent.objects.create(
        aliquot=aliquot, volume_ul=Decimal("100"), consumed_date=date(2025, 2, 1)
    )
    assert ce.pipeline_run_id is None


def test_consumption_links_pipeline_run(aliquot):
    run = PipelineRun.objects.create()
    ce = ConsumptionEvent.objects.create(
        aliquot=aliquot, volume_ul=Decimal("100"), consumed_date=date(2025, 2, 1),
        pipeline_run=run,
    )
    ce.refresh_from_db()
    assert ce.pipeline_run_id == run.pk


# --- Opportunistic visit anchor (slice 03) ---


def test_aliquot_recipient_visit_fk_is_nullable_protect(aliquot):
    f = Aliquot._meta.get_field("recipient_visit")
    assert f.null and f.blank
    assert f.remote_field.on_delete is models.PROTECT


def test_aliquot_attaches_to_recipient_visit(anchored_aliquot):
    assert anchored_aliquot.recipient_visit is not None
    assert anchored_aliquot.recipient_visit.recipient.subject_id == "SCMVR07"


# --- History (consistency with every prior outcome model) ---


def test_history_tracked(aliquot):
    assert aliquot.history.count() == 1
    ThawEvent.objects.create(aliquot=aliquot, thawed_date=date(2025, 2, 1))
    ce = ConsumptionEvent.objects.create(
        aliquot=aliquot, volume_ul=Decimal("100"), consumed_date=date(2025, 2, 2)
    )
    assert ce.history.count() == 1
