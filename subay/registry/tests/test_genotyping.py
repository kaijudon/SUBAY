"""Slice 10 — Genotyping ingest: models.

`GenotypingResult` anchors to the source `Aliquot`; subject and sample-date are
DERIVED through the tube (never stored). A mixed infection is multiple
`GenotypeCall` rows (1NF). Sanger loci carry R/F/N; qPCR per-probe P/N/I rolls up
to single/mixed/untyped. Raw `.ab1` is append-only. No call is finalized without a
second-reviewer lock set by a DIFFERENT user; the qPCR reviewer gate is scoped to
`I` readings only. The Ross 2020 reference set is SHA-pinned.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction

from subay.registry.models import (
    QPCR_PROBE_CHOICES,
    SANGER_CALL_CHOICES,
    Aliquot,
    CMVQuantitative,
    GenotypeCall,
    GenotypingResult,
    PipelineRun,
    QpcrDetail,
    QpcrProbeReading,
    Recipient,
    RecipientVisit,
    ReferenceAccession,
    ReferenceSet,
    SangerDetail,
)


@pytest.fixture
def editor(db):
    return User.objects.create_user(username="bioinformatician")


@pytest.fixture
def reviewer(db):
    return User.objects.create_user(username="reviewing_clinician")


@pytest.fixture
def anchored_aliquot(db):
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


@pytest.fixture
def result(anchored_aliquot):
    run = PipelineRun.objects.create(input_manifest_sha256="a" * 64)
    return GenotypingResult.objects.create(
        aliquot=anchored_aliquot, pipeline_run=run, assay_type="sanger"
    )


# --- AC1: anchor through the tube; subject/date derived; optional episode FK ---


def test_subject_and_sample_date_derived_through_tube(result):
    assert result.subject.subject_id == "SCMVR07"
    assert result.sample_date == date(2025, 1, 15)


def test_no_stored_subject_or_date_column():
    field_names = {f.name for f in GenotypingResult._meta.get_fields()}
    assert "subject_id" not in field_names
    assert "sample_date" not in field_names
    assert "drawn_date" not in field_names
    assert isinstance(GenotypingResult.subject, property)
    assert isinstance(GenotypingResult.sample_date, property)


def test_cmv_episode_anchor_is_nullable_set_null(result):
    f = GenotypingResult._meta.get_field("cmv_episode_anchor")
    assert f.null and f.blank
    assert f.remote_field.on_delete is models.SET_NULL
    assert f.related_model is CMVQuantitative


def test_aliquot_fk_is_protect(anchored_aliquot, result):
    f = GenotypingResult._meta.get_field("aliquot")
    assert f.remote_field.on_delete is models.PROTECT
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            anchored_aliquot.delete()


# --- AC2: mixed infection = multiple GenotypeCall rows (1NF) ---


def test_mixed_infection_two_calls_same_locus(result, editor):
    GenotypeCall.objects.create(result=result, locus="gB", allele="gB1", entered_by=editor)
    GenotypeCall.objects.create(result=result, locus="gB", allele="gB3", entered_by=editor)
    assert result.calls.count() == 2


# --- AC3: locked dual taxonomy + rollup ---


def test_locked_taxonomies():
    assert {c for c, _ in SANGER_CALL_CHOICES} == {"R", "F", "N"}
    assert {c for c, _ in QPCR_PROBE_CHOICES} == {"P", "N", "I"}


def test_illegal_sanger_code_rejected(result, editor):
    call = GenotypeCall(result=result, locus="gB", allele="gB1", sanger_call="X", entered_by=editor)
    with pytest.raises(ValidationError):
        call.full_clean()


def test_qpcr_rollup_single_mixed_untyped(result):
    detail = QpcrDetail.objects.create(result=result)
    assert detail.rollup == "untyped"
    QpcrProbeReading.objects.create(qpcr_detail=detail, probe="gB1", call="P")
    assert detail.rollup == "single"
    QpcrProbeReading.objects.create(qpcr_detail=detail, probe="gB3", call="P")
    assert detail.rollup == "mixed"


# --- AC4: raw .ab1 append-only; consensus attributed ---


def test_raw_ab1_is_append_only(result, editor):
    sd = SangerDetail.objects.create(
        result=result, raw_ab1_sha256="b" * 64, raw_ab1_path="b" * 64,
        consensus_sequence="ACGT", edited_by=editor,
    )
    sd.raw_ab1_sha256 = "c" * 64  # attempt to overwrite the raw reference
    with pytest.raises(ValidationError):
        sd.full_clean()


def test_duplicate_raw_ab1_sha_rejected_by_db(result):
    SangerDetail.objects.create(result=result, raw_ab1_sha256="d" * 64, raw_ab1_path="d" * 64)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SangerDetail.objects.create(
                result=result, raw_ab1_sha256="d" * 64, raw_ab1_path="other"
            )


def test_consensus_carries_editor(result, editor):
    sd = SangerDetail.objects.create(
        result=result, raw_ab1_sha256="e" * 64, raw_ab1_path="e" * 64, edited_by=editor
    )
    assert sd.edited_by_id == editor.pk


# --- AC5: second-reviewer lock, different user ---


def test_lock_same_user_rejected(result, editor):
    call = GenotypeCall(
        result=result, locus="gB", allele="gB1", entered_by=editor,
        verified_by=editor, verified_at=date(2025, 2, 1), is_verified=True,
    )
    with pytest.raises(ValidationError):
        call.full_clean()


def test_lock_null_reviewer_rejected(result, editor):
    call = GenotypeCall(
        result=result, locus="gB", allele="gB1", entered_by=editor, is_verified=True
    )
    with pytest.raises(ValidationError):
        call.full_clean()


def test_lock_different_user_saves(result, editor, reviewer):
    call = GenotypeCall(
        result=result, locus="gB", allele="gB1", entered_by=editor,
        verified_by=reviewer, verified_at=date(2025, 2, 1), is_verified=True,
    )
    call.full_clean()
    call.save()
    assert call.pk is not None


def test_locked_call_content_is_frozen(result, editor, reviewer):
    """A verified call's allele content cannot be edited (clean() freeze guard,
    mirroring SangerDetail append-only). Lock reads as 'frozen', so make it so."""
    call = GenotypeCall.objects.create(
        result=result, locus="gB", allele="gB1", entered_by=editor,
        verified_by=reviewer, verified_at=date(2025, 2, 1), is_verified=True,
    )
    call.allele = "gB99_TAMPERED"
    with pytest.raises(ValidationError):
        call.full_clean()


def test_locked_call_cannot_be_unlocked_and_edited(result, editor, reviewer):
    """Freeze keys off the STORED lock, so unlock-and-edit in one save is blocked."""
    call = GenotypeCall.objects.create(
        result=result, locus="gB", allele="gB1", entered_by=editor,
        verified_by=reviewer, verified_at=date(2025, 2, 1), is_verified=True,
    )
    call.is_verified = False
    call.allele = "gB99_TAMPERED"
    with pytest.raises(ValidationError):
        call.full_clean()


def test_lock_same_user_rejected_by_db(result, editor):
    """DB-layer belt-and-suspenders: same editor/reviewer when verified is rejected."""
    call = GenotypeCall(
        result=result, locus="gB", allele="gB1", entered_by=editor,
        verified_by=editor, verified_at=date(2025, 2, 1), is_verified=True,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            call.save()


# --- AC6: qPCR reviewer gate scoped to I only ---


def test_clean_pn_reading_needs_no_reviewer(result):
    detail = QpcrDetail.objects.create(result=result)
    reading = QpcrProbeReading(qpcr_detail=detail, probe="gB1", call="P")
    reading.full_clean()  # clean P needs no second review


def test_indeterminate_reading_requires_reviewer(result, editor):
    detail = QpcrDetail.objects.create(result=result)
    reading = QpcrProbeReading(qpcr_detail=detail, probe="gB1", call="I", entered_by=editor)
    with pytest.raises(ValidationError):
        reading.full_clean()


def test_indeterminate_reading_with_different_reviewer_ok(result, editor, reviewer):
    detail = QpcrDetail.objects.create(result=result)
    reading = QpcrProbeReading(
        qpcr_detail=detail, probe="gB1", call="I", entered_by=editor,
        reviewed_by=reviewer, reviewed_at=date(2025, 2, 1),
    )
    reading.full_clean()


def test_indeterminate_reading_reviewer_enforced_at_db(result, editor):
    """DB CheckConstraint blocks a bare .save() of an 'I' reading with no
    reviewer — clean() alone is bypassable (mirrors GenotypeCall's lock)."""
    detail = QpcrDetail.objects.create(result=result)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            QpcrProbeReading.objects.create(
                qpcr_detail=detail, probe="gB1", call="I", entered_by=editor
            )


def test_indeterminate_reading_self_review_blocked_at_db(result, editor):
    """DB CheckConstraint blocks a self-review (reviewer == editor) on a bare save."""
    detail = QpcrDetail.objects.create(result=result)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            QpcrProbeReading.objects.create(
                qpcr_detail=detail, probe="gB1", call="I", entered_by=editor,
                reviewed_by=editor, reviewed_at=date(2025, 2, 1),
            )


# --- AC10: Ross 2020 reference set SHA-pinned ---


def test_reference_set_sha_pinned(db):
    rs = ReferenceSet.objects.create(
        name="Ross 2020", citation="Ross SA et al.", content_sha256="f" * 64
    )
    ReferenceAccession.objects.create(reference_set=rs, accession="X04650", genotype="gB1")
    assert rs.content_sha256 == "f" * 64


def test_reference_set_content_sha_immutable(db):
    rs = ReferenceSet.objects.create(name="Ross 2020", content_sha256="f" * 64)
    rs.content_sha256 = "0" * 64  # tampering
    with pytest.raises(ValidationError):
        rs.full_clean()


def test_reference_set_content_sha_immutable_via_update(db):
    """The append-only clean() guard is bypassable by QuerySet.update(); the
    AppendOnlyQuerySet manager closes that ORM vector."""
    rs = ReferenceSet.objects.create(name="Ross 2020", content_sha256="f" * 64)
    with pytest.raises(ValueError):
        ReferenceSet.objects.filter(pk=rs.pk).update(content_sha256="0" * 64)
    # a non-immutable field still updates fine
    assert ReferenceSet.objects.filter(pk=rs.pk).update(citation="updated") == 1


def test_sanger_raw_ref_immutable_via_update(result):
    sd = SangerDetail.objects.create(
        result=result, raw_ab1_sha256="b" * 64, raw_ab1_path="b" * 64
    )
    with pytest.raises(ValueError):
        SangerDetail.objects.filter(pk=sd.pk).update(raw_ab1_sha256="c" * 64)
    with pytest.raises(ValueError):
        SangerDetail.objects.filter(pk=sd.pk).update(raw_ab1_path="elsewhere")
    # consensus is editable, not append-only
    assert SangerDetail.objects.filter(pk=sd.pk).update(consensus_sequence="ACGT") == 1


def test_reference_accession_unique_per_set(db):
    rs = ReferenceSet.objects.create(name="Ross 2020", content_sha256="f" * 64)
    ReferenceAccession.objects.create(reference_set=rs, accession="X04650", genotype="gB1")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ReferenceAccession.objects.create(
                reference_set=rs, accession="X04650", genotype="gB2"
            )


# --- History (consistency with every prior outcome model) ---


def test_history_tracked(result, editor):
    assert result.history.count() == 1
    call = GenotypeCall.objects.create(result=result, locus="gB", allele="gB1", entered_by=editor)
    assert call.history.count() == 1
