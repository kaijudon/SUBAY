"""Slice 10 — `ingest_genotyping` management command.

A Bioinformatician loads one pipeline run's results: all-or-nothing (a mid-import
failure rolls back with no half-written rows), idempotent (a re-run duplicates
nothing), content-addressed (stored file name == content SHA-256, identical bytes
dedup) under `MEDIA_ROOT`, and closing the slice-09 consumption→run custody link.
"""
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError

from renova.registry.models import (
    Aliquot,
    ConsumptionEvent,
    GenotypeCall,
    GenotypingResult,
    PipelineRun,
    Recipient,
    RecipientVisit,
    SangerDetail,
)

AB1_BYTES = b"ABIF\x00\x01raw-trace-bytes"
AB1_SHA = hashlib.sha256(AB1_BYTES).hexdigest()


@pytest.fixture
def editor(db):
    return User.objects.create_user(username="bioinformatician")


@pytest.fixture
def aliquot(db):
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


def _write_bundle(tmp_path, results):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "sample1.ab1").write_bytes(AB1_BYTES)
    manifest = {
        "tool_versions": "BioEdit 7.2; MAFFT 7.5",
        "reference_set": {
            "name": "Ross 2020",
            "citation": "Ross SA et al. 2020",
            "content_sha256": "f" * 64,
            "accessions": [{"accession": "X04650", "genotype": "gB1"}],
        },
        "results": results,
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    return bundle / "manifest.json"


def _sanger_result(aliquot_id, consumption_event_id=None):
    return {
        "aliquot_id": aliquot_id,
        "consumption_event_id": consumption_event_id,
        "assay_type": "sanger",
        "entered_by": "bioinformatician",
        "calls": [{"locus": "gB", "allele": "gB1", "sanger_call": "R"}],
        "sanger": [{"raw_ab1": "sample1.ab1", "consensus": "ACGT"}],
        "qpcr": [],
    }


# --- AC9: content-addressed, dedup, MEDIA_ROOT ---


def test_happy_path_content_addressed(aliquot, editor, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    manifest = _write_bundle(tmp_path, [_sanger_result(aliquot.pk)])

    call_command("ingest_genotyping", str(manifest))

    assert PipelineRun.objects.count() == 1
    assert GenotypingResult.objects.count() == 1
    assert GenotypeCall.objects.count() == 1
    assert SangerDetail.objects.count() == 1

    stored = Path(settings.MEDIA_ROOT) / AB1_SHA  # filename == sha256(content)
    assert stored.exists()
    assert stored.read_bytes() == AB1_BYTES
    assert str(stored).startswith(settings.MEDIA_ROOT)


# --- AC7: all-or-nothing rollback ---


def test_mid_import_failure_rolls_back(aliquot, editor, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    good = _sanger_result(aliquot.pk)
    bad = _sanger_result(aliquot.pk)
    bad["assay_type"] = "bogus"  # invalid -> full_clean fails on the 2nd record
    manifest = _write_bundle(tmp_path, [good, bad])

    with pytest.raises(CommandError):
        call_command("ingest_genotyping", str(manifest))

    assert PipelineRun.objects.count() == 0
    assert GenotypingResult.objects.count() == 0
    assert GenotypeCall.objects.count() == 0
    assert SangerDetail.objects.count() == 0
    # The staged file copy is unwound on failure.
    media = tmp_path / "media"
    assert not media.exists() or not list(media.iterdir())


# --- AC8: idempotent re-run + AC9 dedup on disk ---


def test_idempotent_rerun(aliquot, editor, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    manifest = _write_bundle(tmp_path, [_sanger_result(aliquot.pk)])

    call_command("ingest_genotyping", str(manifest))
    counts = (
        PipelineRun.objects.count(), GenotypingResult.objects.count(),
        GenotypeCall.objects.count(), SangerDetail.objects.count(),
    )
    call_command("ingest_genotyping", str(manifest))  # same input again

    assert counts == (
        PipelineRun.objects.count(), GenotypingResult.objects.count(),
        GenotypeCall.objects.count(), SangerDetail.objects.count(),
    )
    # Identical bytes collapse to one stored file on disk.
    stored = list((tmp_path / "media").glob(AB1_SHA))
    assert len(stored) == 1


# --- AC11: consumption event links the created run ---


def test_consumption_event_links_run(aliquot, editor, tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    ce = ConsumptionEvent.objects.create(
        aliquot=aliquot, volume_ul=Decimal("100"), consumed_date=date(2025, 2, 1)
    )
    manifest = _write_bundle(tmp_path, [_sanger_result(aliquot.pk, consumption_event_id=ce.pk)])

    call_command("ingest_genotyping", str(manifest))

    ce.refresh_from_db()
    run = PipelineRun.objects.get()
    assert ce.pipeline_run_id == run.pk
