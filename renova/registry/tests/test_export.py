import csv
import hashlib
import json
from datetime import date
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from renova.registry.models import (
    ClosureDay,
    CMVQuantitative,
    CMVSerology,
    Donor,
    DonorVisit,
    OtherCondition,
    Recipient,
    RecipientVisit,
)


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
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 15)
    )
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
    assert names == {
        "recipient.csv",
        "donor.csv",
        "recipientvisit.csv",
        "donorvisit.csv",
        "cmvserology.csv",
        "cmvquantitative.csv",
        "othercondition.csv",
        "manifest.json",
    }

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


# --- Slice 02: baseline + derived values flow through the de-id export ---


@pytest.fixture
def seeded_baseline(db):
    """A recipient with confounders + a paired donor (mismatching serology) +
    a long OtherCondition row — the full Slice 02 baseline surface."""
    d = Donor.objects.create(
        subject_id="DCMVD01",
        date_of_birth=date(1975, 1, 1),
        sex="F",
        donor_type="living",
        relation="sibling",
    )
    CMVSerology.objects.create(donor=d, value=Decimal("1.0"), drawn_date=date(2024, 12, 1))  # NEG
    r = Recipient.objects.create(
        subject_id="SCMVR07",
        date_of_birth=date(1980, 1, 1),
        sex="M",
        kt_date=date(2025, 1, 1),
        donor=d,
        donor_serostatus="POS",  # disagrees with donor's NEG serology -> mismatch
        recipient_serostatus="NEG",
        has_diabetes=False,  # explicitly "no"
        has_hypertension=None,  # not asked
        dialysis_vintage_months=24,
        induction_agent="none",
    )
    OtherCondition.objects.create(recipient=r, condition="gout")
    return r


def test_export_distinguishes_no_from_not_asked(seeded_baseline, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    with (out / "recipient.csv").open(newline="") as fh:
        row = list(csv.DictReader(fh))[0]
    # has_diabetes=False is a non-empty, distinct cell; has_hypertension=None is blank.
    assert row["has_diabetes"] == "false"
    assert row["has_hypertension"] == ""
    assert row["has_diabetes"] != row["has_hypertension"]


def test_export_materializes_baseline_and_derived(seeded_baseline, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    with (out / "recipient.csv").open(newline="") as fh:
        row = list(csv.DictReader(fh))[0]
    assert row["dialysis_vintage_months"] == "24"
    assert row["induction_agent"] == "none"
    assert row["has_donor_serostatus_mismatch"] == "true"  # POS vs NEG
    assert row["donor"] == "DCMVD01"

    with (out / "donor.csv").open(newline="") as fh:
        drow = list(csv.DictReader(fh))[0]
    assert drow["donor_type"] == "living"
    assert drow["relation"] == "sibling"
    assert drow["baseline_serostatus"] == "NEG"


def test_export_othercondition_is_one_row_per_condition(seeded_baseline, tmp_path):
    OtherCondition.objects.create(recipient=seeded_baseline, condition="prior cmv")
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    with (out / "othercondition.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert {r["condition"] for r in rows} == {"gout", "prior cmv"}
    assert all(r["recipient"] == "SCMVR07" for r in rows)


def test_export_de_id_leak_scan_over_new_columns_and_file(seeded_baseline, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    for f in out.glob("*.csv"):
        text = f.read_text()
        assert "2025-01-01" not in text  # kt_date never as a calendar date
        assert "2024-12-01" not in text  # donor drawn_date
        assert "1980-01-01" not in text  # dob
        assert "1975-01-01" not in text  # donor dob


def test_export_refuses_on_leaky_other_condition(db, tmp_path):
    r = Recipient.objects.create(
        subject_id="SCMVR07",
        date_of_birth=date(1980, 1, 1),
        sex="M",
        kt_date=date(2025, 1, 1),
    )
    OtherCondition.objects.create(recipient=r, condition="Maria Santos")  # name-shaped leak

    with pytest.raises(CommandError):
        call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    assert not (tmp_path / "v0.1").exists()


# --- Slice 03: visit spine + closure-shift fields flow through the de-id export ---


@pytest.fixture
def seeded_visits(db):
    """A recipient with a closure-shifted visit (a ClosureDay carrying a
    free-text reference) AND a donor with a real draw_date — the full Slice 03
    export surface for the leak scan."""
    d = Donor.objects.create(
        subject_id="DCMVD01", date_of_birth=date(1975, 1, 1), sex="F"
    )
    DonorVisit.objects.create(donor=d, draw_date=date(2024, 12, 1))
    r = Recipient.objects.create(
        subject_id="SCMVR07",
        date_of_birth=date(1980, 1, 1),
        sex="M",
        kt_date=date(2025, 1, 1),
    )
    ClosureDay.objects.create(
        date=date(2025, 1, 8), reason="annexed_holiday", reference="Annex A clause 3"
    )
    RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 9)
    )
    return r


def test_export_visit_columns_are_offsets_and_derived(seeded_visits, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    with (out / "recipientvisit.csv").open(newline="") as fh:
        row = list(csv.DictReader(fh))[0]
    assert row["recipient"] == "SCMVR07"
    assert row["timepoint_label"] == "day_7"
    assert row["nominal_day"] == "7"
    assert row["actual_day_offset"] == "8"  # 2025-01-09 is 8 days after kt day 0
    assert row["closure_shifted"] == "true"
    assert row["closure_reason"] == "annexed_holiday"
    assert row["shift_days_from_nominal"] == "1"  # actual 01-09 minus nominal 01-08
    assert row["completion_status"] == "completed"


def test_export_donor_visit_has_no_calendar_date(seeded_visits, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    with (out / "donorvisit.csv").open(newline="") as fh:
        row = list(csv.DictReader(fh))[0]
    assert row["donor"] == "DCMVD01"
    assert row["day_offset"] == ""  # no kt anchor -> no offset, no calendar date


def test_export_stretch_reference_never_exported(seeded_visits, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    # free-text reference is a leak vector — the enum closure_reason carries the signal.
    for f in out.glob("*.csv"):
        assert "Annex A clause 3" not in f.read_text()


def test_export_leak_scan_over_visit_columns_and_donor_file(seeded_visits, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for f in out.glob("*.csv"):
        text = f.read_text()
        assert "2025-01-09" not in text  # actual_visit_date never a calendar date
        assert "2025-01-08" not in text  # nominal/closure date
        assert "2024-12-01" not in text  # donor draw_date absent (blanked)
        assert "2025-01-01" not in text  # kt_date


def test_export_refuses_on_leaky_closure_reason_in_exported_column(db, tmp_path):
    """A name-shaped value placed in an EXPORTED column still triggers refusal
    with nothing written (the chokepoint stays intact)."""
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=date(2025, 1, 1),
    )
    # completion_status is exported; a leaky value there must be caught.
    v = RecipientVisit(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8),
        completion_status="Maria Santos",
    )
    v.save()  # bypass clean() to stage a leak into an exported column
    with pytest.raises(CommandError):
        call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    assert not (tmp_path / "v0.1").exists()


# --- Slice 04: completer cohort + missing observation flow through the export ---


@pytest.fixture
def seeded_cohort(db):
    """One completed recipient and one withdrawn recipient — both
    sequencing-included — plus a missing-observation serology. Lets a test show
    the Obj 1 completer count differs from the Obj 5 all-sequenced count."""
    r1 = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=date(2025, 1, 1), completion_status="completed",
    )
    r2 = Recipient.objects.create(
        subject_id="SCMVR08", date_of_birth=date(1981, 1, 1), sex="F",
        kt_date=date(2025, 1, 1), completion_status="withdrawn",
    )
    v = RecipientVisit.objects.create(
        recipient=r1, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8)
    )
    CMVSerology.objects.create(
        recipient_visit=v, result_status="missing", drawn_date=date(2025, 1, 8)
    )
    return r1, r2


def test_export_exposes_completion_status_and_sequencing_flag(seeded_cohort, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    with (out / "recipient.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert "completion_status" in rows[0]
    assert "sequencing_included" in rows[0]

    completers = [r for r in rows if r["completion_status"] == "completed"]
    sequenced = [r for r in rows if r["sequencing_included"] == "true"]
    # Both are sequencing-included, but only one completed: the denominators differ.
    assert len(completers) == 1
    assert len(sequenced) == 2
    assert len(completers) != len(sequenced)


def test_export_serology_marks_missing_observation(seeded_cohort, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    with (out / "cmvserology.csv").open(newline="") as fh:
        row = list(csv.DictReader(fh))[0]
    assert row["result_status"] == "missing"
    assert row["value"] == ""  # a missing observation carries no value


def test_export_slice04_columns_have_no_calendar_date_or_identifier(seeded_cohort, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for f in out.glob("*.csv"):
        text = f.read_text()
        assert "2025-01-01" not in text  # kt_date
        assert "2025-01-08" not in text  # drawn/visit date
        assert "1980-01-01" not in text  # dob
        assert "1981-01-01" not in text  # dob


# --- Slice 05: viral-load + IgM serology + pre-KT serostatus flow through export ---


@pytest.fixture
def seeded_slice05(db):
    """A recipient with a pre_kt IgG+IgM serology and a viral-load series, plus a
    donor with its own quantitative result — the full Slice 05 export surface."""
    d = Donor.objects.create(subject_id="DCMVD01", date_of_birth=date(1975, 1, 1), sex="F")
    CMVQuantitative.objects.create(donor=d, value=Decimal("200"), drawn_date=date(2024, 12, 1))
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="pre_kt", actual_visit_date=date(2025, 1, 1)
    )
    CMVSerology.objects.create(
        recipient_visit=v, value=Decimal("3.0"),  # IgG positive
        igm_value=Decimal("1.0"), igm_status="reported",  # IgM negative
        drawn_date=date(2025, 1, 1),
    )
    CMVQuantitative.objects.create(
        recipient_visit=v, value=Decimal("1500"), drawn_date=date(2025, 1, 1)
    )
    return r


def test_export_serology_has_materialized_igm_columns(seeded_slice05, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    with (out / "cmvserology.csv").open(newline="") as fh:
        row = list(csv.DictReader(fh))[0]
    assert row["igm_value"] == "1.00"
    assert row["igm_status"] == "reported"
    assert row["igm_positive"] == "False"  # materialized derived value, 1.0 < 2.0


def test_export_materializes_pre_kt_igg_serostatus(seeded_slice05, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    with (out / "recipient.csv").open(newline="") as fh:
        row = list(csv.DictReader(fh))[0]
    assert row["pre_kt_igg_serostatus"] == "POS"  # IgG 3.0 >= 2.0


def test_export_quantitative_is_long_one_row_per_result(seeded_slice05, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    with (out / "cmvquantitative.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2  # one donor row, one recipient-visit row
    by_parent = {r["parent_type"] for r in rows}
    assert by_parent == {"donor", "recipient_visit"}


def test_export_quantitative_recipient_row_is_day_offset(seeded_slice05, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    with (out / "cmvquantitative.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    recip = [r for r in rows if r["parent_type"] == "recipient_visit"][0]
    assert recip["day_offset"] == "0"  # drawn 2025-01-01 == kt day 0
    donor = [r for r in rows if r["parent_type"] == "donor"][0]
    assert donor["day_offset"] == ""  # no kt anchor -> blank, never a calendar date


def test_export_slice05_leak_scan_over_new_file_and_columns(seeded_slice05, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for f in out.glob("*.csv"):
        text = f.read_text()
        assert "2025-01-01" not in text  # kt_date / drawn_date never a calendar date
        assert "2024-12-01" not in text  # donor drawn_date blanked
        assert "1980-01-01" not in text  # dob
        assert "1975-01-01" not in text  # donor dob


def test_export_manifest_lists_quantitative_file(seeded_slice05, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    manifest = json.loads((out / "manifest.json").read_text())
    assert "cmvquantitative.csv" in manifest["files"]
    assert manifest["files"]["cmvquantitative.csv"]["columns"]["parent_id"] == "c"
