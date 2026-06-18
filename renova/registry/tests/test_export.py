import csv
import hashlib
import json
from datetime import date
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from renova.registry.models import CMVSerology, Recipient, RecipientVisit


@pytest.fixture
def seeded(db):
    r = Recipient.objects.create(
        subject_id="SCMVR07",
        date_of_birth=date(1980, 1, 1),
        sex="M",
        kt_date=date(2025, 1, 1),
        donor_serostatus="POS",
        recipient_serostatus="NEG",
    )
    v = RecipientVisit.objects.create(recipient=r, visit_date=date(2025, 1, 15))
    CMVSerology.objects.create(recipient_visit=v, value=Decimal("3.0"), drawn_date=date(2025, 1, 15))
    return r


def test_export_writes_day_offsets_and_no_calendar_date(seeded, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    assert "14" in (out / "recipientvisit.csv").read_text()  # 15 Jan is 14 days after kt day 0
    assert "SCMVR07" in (out / "recipient.csv").read_text()  # pseudonym present

    for f in out.glob("*.csv"):
        text = f.read_text()
        assert "2025-01-15" not in text  # no calendar date
        assert "1980-01-01" not in text  # no date of birth


def test_export_refuses_to_overwrite_frozen_version(seeded, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    with pytest.raises(CommandError):
        call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))


def test_export_produces_one_csv_per_model_with_keys_intact(seeded, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    names = {p.name for p in out.iterdir()}
    assert names == {"recipient.csv", "donor.csv", "recipientvisit.csv", "cmvserology.csv", "manifest.json"}

    with (out / "recipientvisit.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["recipient"] == "SCMVR07"  # FK key intact, not joined/flattened


def test_export_materializes_age_and_risk_stratum(seeded, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    with (out / "recipient.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    row = rows[0]
    assert row["age"] == str(seeded.age)
    assert row["risk_stratum"] == seeded.risk_stratum


def test_export_csv_is_plain_text_and_parseable(seeded, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    for path in out.glob("*.csv"):
        with path.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        assert reader.fieldnames  # header decodes cleanly

    with (out / "recipient.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) >= 1  # at least one data row decodes cleanly


def test_export_same_db_state_reproduces_identical_sha256(seeded, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    call_command("export_analysis_set", "v0.2", outdir=str(tmp_path))

    out1, out2 = tmp_path / "v0.1", tmp_path / "v0.2"
    for name in ["recipient.csv", "donor.csv", "recipientvisit.csv", "cmvserology.csv"]:
        h1 = hashlib.sha256((out1 / name).read_bytes()).hexdigest()
        h2 = hashlib.sha256((out2 / name).read_bytes()).hexdigest()
        assert h1 == h2


def test_export_manifest_has_row_counts_sha256_and_column_types(seeded, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    manifest = json.loads((out / "manifest.json").read_text())
    for name in ["recipient.csv", "donor.csv", "recipientvisit.csv", "cmvserology.csv"]:
        path = out / name
        entry = manifest["files"][name]

        text = path.read_text()
        expected_row_count = max(len(text.splitlines()) - 1, 0)
        assert entry["row_count"] == expected_row_count

        expected_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        assert entry["sha256"] == expected_sha256

    assert manifest["files"]["recipient.csv"]["columns"]["subject_id"] == "c"
    assert manifest["files"]["donor.csv"]["columns"]["subject_id"] == "c"


@pytest.mark.parametrize("leaky_subject_id", ["Maria Santos", "MRN-445566", "12 Rizal St"])
def test_export_refuses_on_seeded_identifier(leaky_subject_id, db, tmp_path):
    Recipient.objects.create(
        subject_id=leaky_subject_id,
        date_of_birth=date(1980, 1, 1),
        sex="M",
        kt_date=date(2025, 1, 1),
    )

    with pytest.raises(CommandError):
        call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))

    assert not (tmp_path / "v0.1").exists()
    assert list(tmp_path.glob(".v0.1.staging-*")) == []
