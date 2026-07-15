"""Slice 13 — the reusable four-eyes VerificationMixin (US 68).

`entered_by != verified_by`, enforced at BOTH layers (clean() for a friendly
admin/forms error and a DB CheckConstraint for an unbreakable guarantee on the
shell/ingest bare-save path), mirroring the GenotypeCall/ConsumptionEvent
dual-guard idiom. Fields are nullable (DEC-023): the gate bites ONLY when
is_verified=True, so the many existing un-attributed fixtures keep passing.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from subay.registry.models import (
    Aliquot,
    CMVQuantitative,
    CMVSerology,
    ConcordancePair,
    DrugLevel,
    GenotypeCall,
    GenotypingResult,
    Hospitalization,
    PipelineRun,
    Recipient,
    RecipientVisit,
    RejectionEpisode,
    RenalFunction,
    ResistanceCall,
    TBNKPanel,
    VerificationMixin,
)

# The four outcome-critical model families the mixin attaches to (AC2).
MIXED_MODELS = [CMVSerology, DrugLevel, RejectionEpisode, GenotypeCall]


@pytest.fixture
def users(db):
    u1 = User.objects.create_user(username="alice_entry")
    u2 = User.objects.create_user(username="bob_review")
    return u1, u2


@pytest.fixture
def recipient(db):
    return Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )


@pytest.fixture
def visit(recipient):
    return RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_7", actual_visit_date=date(2025, 1, 15)
    )


def _genotype_result(visit):
    a = Aliquot.objects.create(
        recipient_visit=visit, matrix="plasma", collected_date=date(2025, 1, 15),
        initial_volume_ul=Decimal("1000"),
    )
    n = PipelineRun.objects.count()  # deterministic unique manifest sha
    run = PipelineRun.objects.create(input_manifest_sha256=f"{n:064d}")
    return GenotypingResult.objects.create(aliquot=a, pipeline_run=run, assay_type="sanger")


def _build(model, visit, recipient, **verif):
    """An unsaved mixed-in row with the given verification kwargs, every other
    required field already valid so full_clean() exercises only the gate."""
    if model is CMVSerology:
        return CMVSerology(
            recipient_visit=visit, value=Decimal("3.0"), result_status="reported",
            drawn_date=date(2025, 1, 15), **verif,
        )
    if model is DrugLevel:
        return DrugLevel(
            recipient_visit=visit, analyte="tacrolimus", value=Decimal("8.0"),
            result_status="reported", drawn_date=date(2025, 1, 15), **verif,
        )
    if model is RejectionEpisode:
        return RejectionEpisode(
            recipient=recipient, onset_date=date(2025, 2, 1), rejection_type="tcmr", **verif,
        )
    if model is GenotypeCall:
        return GenotypeCall(result=_genotype_result(visit), locus="gB", allele="gB1", **verif)
    raise AssertionError(model)


# --- AC1: the mixin is abstract and enforces entered_by != verified_by ---


def test_mixin_is_abstract():
    assert VerificationMixin._meta.abstract is True


@pytest.mark.parametrize("model", MIXED_MODELS)
def test_same_user_verify_rejected_clean(model, users, visit, recipient):
    u1, _ = users
    obj = _build(model, visit, recipient, is_verified=True, entered_by=u1,
                 verified_by=u1, verified_at=date(2025, 3, 1))
    with pytest.raises(ValidationError):
        obj.full_clean()


@pytest.mark.parametrize("model", MIXED_MODELS)
def test_same_user_verify_rejected_db(model, users, visit, recipient):
    """AC5: a bare .save() (shell/ingest path) is blocked by the DB CheckConstraint."""
    u1, _ = users
    obj = _build(model, visit, recipient, is_verified=True, entered_by=u1,
                 verified_by=u1, verified_at=date(2025, 3, 1))
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            obj.save()


@pytest.mark.parametrize("model", MIXED_MODELS)
def test_verified_requires_verifier_clean(model, users, visit, recipient):
    u1, _ = users
    obj = _build(model, visit, recipient, is_verified=True, entered_by=u1,
                 verified_by=None, verified_at=date(2025, 3, 1))
    with pytest.raises(ValidationError):
        obj.full_clean()


@pytest.mark.parametrize("model", MIXED_MODELS)
def test_verified_requires_timestamp_clean(model, users, visit, recipient):
    u1, u2 = users
    obj = _build(model, visit, recipient, is_verified=True, entered_by=u1,
                 verified_by=u2, verified_at=None)
    with pytest.raises(ValidationError):
        obj.full_clean()


@pytest.mark.parametrize("model", MIXED_MODELS)
def test_verified_requires_verifier_db(model, users, visit, recipient):
    u1, _ = users
    obj = _build(model, visit, recipient, is_verified=True, entered_by=u1,
                 verified_by=None, verified_at=date(2025, 3, 1))
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            obj.save()


@pytest.mark.parametrize("model", MIXED_MODELS)
def test_distinct_verifier_accepted(model, users, visit, recipient):
    u1, u2 = users
    obj = _build(model, visit, recipient, is_verified=True, entered_by=u1,
                 verified_by=u2, verified_at=date(2025, 3, 1))
    obj.full_clean()
    obj.save()
    assert obj.pk is not None


@pytest.mark.parametrize("model", MIXED_MODELS)
def test_unverified_row_needs_no_attribution(model, users, visit, recipient):
    """DEC-023 retrofit-safety: an unverified row needs no attribution at all."""
    obj = _build(model, visit, recipient)
    obj.full_clean()
    obj.save()
    assert obj.is_verified is False
    assert obj.entered_by_id is None
    assert obj.verified_by_id is None


# --- AC2: applied to outcome-critical models ONLY, not every table ---


def test_mixin_applied_to_outcome_critical_models_only():
    for m in (CMVSerology, DrugLevel, RejectionEpisode, GenotypeCall):
        assert issubclass(m, VerificationMixin), m
    for m in (
        CMVQuantitative, TBNKPanel, RenalFunction, Recipient, RecipientVisit,
        Hospitalization, Aliquot, ConcordancePair, ResistanceCall,
    ):
        assert not issubclass(m, VerificationMixin), m
