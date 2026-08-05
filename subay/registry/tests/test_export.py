import csv
import hashlib
import json
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError

from subay.registry.models import (
    Aliquot,
    ClosureDay,
    CMVQuantitative,
    CMVSerology,
    ConcordancePair,
    ConsumptionEvent,
    Donor,
    DonorVisit,
    DrugLevel,
    GenotypeCall,
    GenotypingResult,
    Hospitalization,
    MedicationCourse,
    OtherCondition,
    PipelineRun,
    ProtocolDeviation,
    Recipient,
    RecipientVisit,
    RejectionEpisode,
    ReleaseEvent,
    RenalFunction,
    ResistanceCall,
    ResistanceVariant,
    SequencingAliquot,
    TBNKPanel,
    ThawEvent,
)
from subay.registry.management.commands.export_analysis_set import (
    ADDRESS_RX,
    DATE_RX,
    MRN_RX,
    NAME_RX,
)
from subay.registry.serology_ranges import (
    ADVISORY_EFFECTIVE,
    GEN2_IGG_EQUIVOCAL_FROM_AU_ML,
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
        "tbnkpanel.csv",
        "renalfunction.csv",
        "druglevel.csv",
        "cmvepisode.csv",
        "medicationcourse.csv",
        "rejectionepisode.csv",
        "hospitalization.csv",
        "aliquot.csv",
        "genotypingresult.csv",
        "genotypecall.csv",
        "concordancepair.csv",
        "concordancelocus.csv",
        "resistancecall.csv",
        "resistancevariant.csv",
        "releaseevent.csv",
        "protocoldeviation.csv",
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


def test_leak_scan_covers_manifest_json(tmp_path):
    """The leak sweep scans manifest.json too — a future slice that writes a
    label/path into the manifest must not slip an identifier past the gate."""
    from subay.registry.management.commands.export_analysis_set import Command

    (tmp_path / "manifest.json").write_text(
        json.dumps({"version": "v0.1", "files": {}, "note": "MRN-445566"})
    )
    with pytest.raises(CommandError):
        Command()._assert_no_identifier_leak(tmp_path)


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


def test_export_keeps_the_mismatch_flags_third_state_separable(seeded_baseline, tmp_path):
    """Slice 17 ticket 02 gave has_donor_serostatus_mismatch a third answer, and
    nothing in the export pinned what that answer becomes in the file.

    The column previously wrote "false" for a pair it could not compare, which
    asserted the two sides were checked and agreed. It now names the third state
    outright. Those are different claims and an analyst counting comparable pairs
    depends on the difference, so all three cells are asserted together here
    rather than one at a time: what matters is that no two of them collide.

    Blank is asserted against, not merely differed from. Every other unknown in
    this snapshot is blank, and the manifest publishes column TYPES and no value
    domain, so a blank here would be indistinguishable from a question nobody
    asked to anyone reading the file without the source in front of them. The
    cell is the only place the distinction can live.

    The equivocal-donor case is the one ticket 02 added and the one a donor can
    never resolve, since a donor gets at most one baseline draw.
    """
    equivocal_donor = Donor.objects.create(
        subject_id="DCMVD02", date_of_birth=date(1976, 1, 1), sex="M", donor_type="living"
    )
    CMVSerology.objects.create(
        donor=equivocal_donor,
        value=GEN2_IGG_EQUIVOCAL_FROM_AU_ML,  # grayzone -> no baseline serostatus
        drawn_date=ADVISORY_EFFECTIVE,
    )
    Recipient.objects.create(
        subject_id="SCMVR08", date_of_birth=date(1981, 1, 1), sex="F",
        kt_date=date(2025, 2, 1), donor=equivocal_donor, donor_serostatus="POS",
    )
    agreeing_donor = Donor.objects.create(
        subject_id="DCMVD03", date_of_birth=date(1977, 1, 1), sex="F", donor_type="living"
    )
    CMVSerology.objects.create(
        donor=agreeing_donor, value=Decimal("1.0"), drawn_date=date(2024, 12, 1)  # NEG
    )
    Recipient.objects.create(
        subject_id="SCMVR09", date_of_birth=date(1982, 1, 1), sex="M",
        kt_date=date(2025, 3, 1), donor=agreeing_donor, donor_serostatus="NEG",
    )

    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    with (tmp_path / "v0.1" / "recipient.csv").open(newline="") as fh:
        reader = csv.DictReader(fh)
        rows = {r["subject_id"]: r for r in reader}
    flags = {sid: r["has_donor_serostatus_mismatch"] for sid, r in rows.items()}

    mismatch, not_comparable, agreed = flags["SCMVR07"], flags["SCMVR08"], flags["SCMVR09"]
    assert mismatch == "true"
    assert agreed == "false"
    assert not_comparable == "not_comparable"
    assert len({mismatch, not_comparable, agreed}) == 3
    # And not the blank an unasked question uses two columns to the left.
    assert rows["SCMVR07"]["has_hypertension"] == ""
    assert "" not in {mismatch, not_comparable, agreed}


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
    assert drow["baseline_serostatus"] == "NEG"  # relation (free text) not exported


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
    # Was igm_positive=False. The materialized derived value is now the
    # three-state reading (slice 17): 1.0 AU/mL under 1st-generation reagent,
    # whose only boundary is 2.00, is non-reactive.
    assert row["igm_interpretation"] == "non_reactive"


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


# --- Slice 06: TBNK / renal / drug-level panels flow through the de-id export ---


@pytest.fixture
def seeded_slice06(db):
    """A recipient with a TBNK panel, a renal-function draw, and a drug level,
    plus a donor-attached drug level — the full Slice 06 export surface."""
    d = Donor.objects.create(subject_id="DCMVD01", date_of_birth=date(1975, 1, 1), sex="F")
    DrugLevel.objects.create(
        donor=d, analyte="tacrolimus", value=Decimal("5.0"), drawn_date=date(2024, 12, 1)
    )
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_180", actual_visit_date=date(2025, 6, 1)
    )
    TBNKPanel.objects.create(
        recipient_visit=v, drawn_date=date(2025, 6, 1),
        cd3_count=Decimal("1200"), cd3_pct=Decimal("75"),
        cd3_cd4_count=Decimal("800"), cd3_cd4_pct=Decimal("50"),
        cd3_cd8_count=Decimal("400"), cd3_cd8_pct=Decimal("25"),
        cd19_count=Decimal("160"), cd19_pct=Decimal("10"),
        nk_count=Decimal("240"), nk_pct=Decimal("15"),
        cd4_cd8_dp_count=Decimal("16"), cd4_cd8_dp_pct=Decimal("1"),
        cd4_cd8_dn_count=Decimal("16"), cd4_cd8_dn_pct=Decimal("1"),
    )
    RenalFunction.objects.create(
        recipient_visit=v, serum_creatinine_mg_dl=Decimal("1.0"), drawn_date=date(2025, 6, 1)
    )
    DrugLevel.objects.create(
        recipient_visit=v, analyte="tacrolimus", value=Decimal("8.0"), drawn_date=date(2025, 6, 1)
    )
    return r


def test_export_writes_slice06_files(seeded_slice06, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for name in ("tbnkpanel.csv", "renalfunction.csv", "druglevel.csv"):
        assert (out / name).exists()


def test_export_tbnk_is_wide_with_materialized_ratio(seeded_slice06, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "tbnkpanel.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1  # one wide row carries all seven subsets
    row = rows[0]
    for col in ("cd3_count", "cd3_cd4_count", "cd3_cd8_count", "cd19_count",
                "nk_count", "cd4_cd8_dp_count", "cd4_cd8_dn_count"):
        assert col in row
    assert row["cd4_cd8_ratio"] == "2"  # 800 / 400, materialized derived
    assert row["day_offset"] == "151"  # 2025-06-01 is 151 days after kt day 0


def test_export_renal_has_creatinine_and_materialized_egfr_no_lab_egfr(seeded_slice06, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "renalfunction.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    row = rows[0]
    assert row["serum_creatinine_mg_dl"] == "1.00"
    assert float(row["eGFR"]) == pytest.approx(94.59, abs=0.1)  # materialized CKD-EPI 2021
    # no lab-reported eGFR column exists anywhere in the file
    for col in row:
        assert col == "eGFR" or "egfr" not in col.lower()


def test_export_druglevel_is_long_per_result(seeded_slice06, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "druglevel.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2  # one donor row, one recipient-visit row
    assert {r["parent_type"] for r in rows} == {"donor", "recipient_visit"}
    recip = [r for r in rows if r["parent_type"] == "recipient_visit"][0]
    assert recip["analyte"] == "tacrolimus"
    assert recip["value"] == "8.00"
    assert recip["day_offset"] == "151"
    donor_row = [r for r in rows if r["parent_type"] == "donor"][0]
    assert donor_row["day_offset"] == ""  # no kt anchor -> blank, never a calendar date


def test_export_manifest_lists_slice06_files(seeded_slice06, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    manifest = json.loads((out / "manifest.json").read_text())
    for name in ("tbnkpanel.csv", "renalfunction.csv", "druglevel.csv"):
        assert name in manifest["files"]


def test_export_slice06_leak_scan_over_new_files_and_columns(seeded_slice06, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for f in out.glob("*.csv"):
        text = f.read_text()
        assert "2025-06-01" not in text  # drawn_date never a calendar date
        assert "2024-12-01" not in text  # donor drawn_date blanked
        assert "2025-01-01" not in text  # kt_date
        assert "1980-01-01" not in text  # dob
        assert "1975-01-01" not in text  # donor dob


def test_export_refuses_on_leaky_slice06_column(db, tmp_path):
    """A name-shaped value in an exported Slice 06 column triggers refusal with
    nothing written (the chokepoint stays intact)."""
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8)
    )
    d = DrugLevel(recipient_visit=v, value=Decimal("8.0"), drawn_date=date(2025, 1, 8))
    d.analyte = "Maria Santos"  # name-shaped leak into an exported column
    d.save()  # bypass clean() to stage a leak
    with pytest.raises(CommandError):
        call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    assert not (tmp_path / "v0.1").exists()


# --- Slice 07: derived CMV episodes + subject-level vars flow through the export ---


@pytest.fixture
def seeded_slice07(db):
    """A recipient whose reported QNAT series forms a resolved episode and an open
    (trailing) episode, plus a donor QNAT (no kt anchor -> never an episode). The
    full Slice 07 export surface for the leak scan."""
    d = Donor.objects.create(subject_id="DCMVD01", date_of_birth=date(1975, 1, 1), sex="F")
    CMVQuantitative.objects.create(donor=d, value=Decimal("1500"), drawn_date=date(2024, 12, 1))
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8)
    )
    CMVQuantitative.objects.create(  # day 0 -> opens episode 1
        recipient_visit=v, value=Decimal("1500"), drawn_date=date(2025, 1, 1),
        severity_tier="disease",
    )
    CMVQuantitative.objects.create(  # day 30 -> closes episode 1
        recipient_visit=v, value=Decimal("10"), drawn_date=date(2025, 1, 31)
    )
    CMVQuantitative.objects.create(  # day 200 -> opens episode 2 (open, no end)
        recipient_visit=v, value=Decimal("1500"), drawn_date=date(2025, 7, 20)
    )
    return r


def test_export_writes_episode_file_one_row_per_episode(seeded_slice07, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"

    with (out / "cmvepisode.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2  # donor QNAT contributes no episode row
    assert all(r["recipient"] == "SCMVR07" for r in rows)
    ep1 = rows[0]
    assert ep1["episode_index"] == "1"
    assert ep1["start_day_offset"] == "0"
    assert ep1["end_day_offset"] == "30"
    assert ep1["severity_tier"] == "disease"  # max tier among members


def test_export_open_episode_has_blank_end_offset(seeded_slice07, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "cmvepisode.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    ep2 = rows[1]
    assert ep2["episode_index"] == "2"
    assert ep2["start_day_offset"] == "200"
    assert ep2["end_day_offset"] == ""  # open/right-censored -> blank, never a date


def test_export_recipient_has_subject_level_episode_columns(seeded_slice07, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "recipient.csv").open(newline="") as fh:
        row = list(csv.DictReader(fh))[0]
    assert row["episode_count"] == "2"
    assert row["any_episode_le_6mo"] == "true"  # first episode starts day 0 <= 180
    assert row["time_to_first_episode"] == "0"
    assert row["time_to_first_episode_censored"] == "false"
    assert row["person_time_days"] == "200"  # observed span day 0..200


def test_export_recipient_episode_columns_blank_without_qnat(db, tmp_path):
    Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "recipient.csv").open(newline="") as fh:
        row = list(csv.DictReader(fh))[0]
    for col in ("episode_count", "any_episode_le_6mo", "time_to_first_episode",
                "time_to_first_episode_censored", "person_time_days"):
        assert row[col] == ""  # no reported QNAT -> no summary to materialize


def test_export_manifest_lists_episode_file(seeded_slice07, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    manifest = json.loads((out / "manifest.json").read_text())
    assert "cmvepisode.csv" in manifest["files"]
    assert manifest["files"]["cmvepisode.csv"]["columns"]["recipient"] == "c"


def test_export_slice07_leak_scan_over_episode_file_and_columns(seeded_slice07, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for f in out.glob("*.csv"):
        text = f.read_text()
        assert "2025-01-01" not in text  # kt_date / drawn_date never a calendar date
        assert "2025-01-31" not in text  # episode-end drawn_date -> only a day-offset
        assert "2025-07-20" not in text  # open-episode drawn_date
        assert "1980-01-01" not in text  # dob


def test_export_refuses_on_leaky_severity_tier(db, tmp_path):
    """A name-shaped value placed in severity_tier (bypassing clean()) surfaces in
    cmvepisode.csv and must trigger refusal with nothing written."""
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8)
    )
    q = CMVQuantitative(  # single-member episode -> tier passes through verbatim
        recipient_visit=v, value=Decimal("1500"), drawn_date=date(2025, 1, 1)
    )
    q.severity_tier = "Maria Santos"  # name-shaped leak into an exported column
    q.save()  # bypass clean() to stage a leak
    CMVQuantitative.objects.create(
        recipient_visit=v, value=Decimal("10"), drawn_date=date(2025, 1, 31)
    )
    with pytest.raises(CommandError):
        call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    assert not (tmp_path / "v0.1").exists()


# --- Slice 08: medication courses + rejection episodes + hospitalizations ---


@pytest.fixture
def seeded_slice08(db):
    """A recipient with a prophylaxis course, a treatment IS-change course, a
    biopsy-proven rejection episode, and a hospitalization whose admit window
    overlaps a positive CMV draw with attribution hand-set to that draw. The full
    Slice 08 export surface for the leak scan."""
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    MedicationCourse.objects.create(
        recipient=r, drug_class="antiviral", agent="valganciclovir",
        dose_amount=Decimal("900"), dose_unit="mg", frequency="qd",
        course_type="prophylaxis", start_date=date(2025, 1, 1), end_date=date(2025, 3, 2),
        completed_per_protocol=True,
    )
    MedicationCourse.objects.create(
        recipient=r, drug_class="immunosuppressant", agent="tacrolimus",
        dose_amount=Decimal("2"), dose_unit="mg", frequency="bid",
        course_type="treatment", start_date=date(2025, 4, 1), end_date=date(2025, 4, 15),
        dose_reduction_count=1, dose_reduction_reason="leukopenia",
        change_direction="reduction", cmv_management_intent=True,
    )
    rej = RejectionEpisode.objects.create(
        recipient=r, onset_date=date(2025, 5, 1), rejection_type="tcmr", banff_grade="ia",
        biopsy_proven=True, biopsy_date=date(2025, 5, 2), treatment="steroid pulse",
        resolved_date=date(2025, 5, 20),
    )
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_90", actual_visit_date=date(2025, 4, 5)
    )
    q = CMVQuantitative.objects.create(
        recipient_visit=v, value=Decimal("1500"), drawn_date=date(2025, 4, 5)
    )
    Hospitalization.objects.create(
        recipient=r, admit_date=date(2025, 4, 3), discharge_date=date(2025, 4, 9),
        reason="cmv viremia workup", disposition="discharged_home",
        cmv_attribution=q, rejection_attribution=rej, cmv_attributable=True,
    )
    return r


def test_export_writes_slice08_files(seeded_slice08, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for name in ("medicationcourse.csv", "rejectionepisode.csv", "hospitalization.csv"):
        assert (out / name).exists()


def test_export_medication_course_columns_are_offsets_and_structured(seeded_slice08, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "medicationcourse.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    proph = [r for r in rows if r["course_type"] == "prophylaxis"][0]
    assert proph["recipient"] == "SCMVR07"
    assert proph["drug_class"] == "antiviral"
    assert proph["agent"] == "valganciclovir"
    assert proph["dose_amount"] == "900.00"
    assert proph["dose_unit"] == "mg"
    assert proph["frequency"] == "qd"
    assert proph["start_day_offset"] == "0"  # 2025-01-01 == kt day 0
    assert proph["end_day_offset"] == "60"  # 2025-03-02 is 60 days after kt
    assert proph["duration_days"] == "60"  # derived day-count, not a date
    assert proph["completed_per_protocol"] == "true"

    treat = [r for r in rows if r["course_type"] == "treatment"][0]
    assert treat["change_direction"] == "reduction"
    assert treat["cmv_management_intent"] == "true"
    assert treat["dose_reduction_count"] == "1"
    # dose_reduction_reason (free text) is a leak vector and not exported; the
    # structured dose_reduction_count carries the analyzable signal.
    assert "dose_reduction_reason" not in rows[0].keys()


def test_export_medication_dose_reduction_reason_never_exported(seeded_slice08, tmp_path):
    """dose_reduction_reason is free text -> a leak vector; it must not be a column
    nor have its value reach any file."""
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for f in out.glob("*.csv"):
        assert "leukopenia" not in f.read_text()
    with (out / "medicationcourse.csv").open(newline="") as fh:
        assert "dose_reduction_reason" not in csv.DictReader(fh).fieldnames


def test_export_rejection_treatment_never_exported(seeded_slice08, tmp_path):
    """treatment is free text -> a leak vector; rejection_type + banff_grade carry
    the signal."""
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for f in out.glob("*.csv"):
        assert "steroid pulse" not in f.read_text()
    with (out / "rejectionepisode.csv").open(newline="") as fh:
        assert "treatment" not in csv.DictReader(fh).fieldnames


def test_export_donor_relation_never_exported(seeded_baseline, tmp_path):
    """relation is free text -> a leak vector; donor_type carries the signal."""
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for f in out.glob("*.csv"):
        assert "sibling" not in f.read_text()
    with (out / "donor.csv").open(newline="") as fh:
        assert "relation" not in csv.DictReader(fh).fieldnames


def test_export_refuses_on_slash_format_date_in_free_text(db, tmp_path):
    """The leak scanner must catch a US/EU slash-format date (not just ISO) in any
    exported free-text cell. OtherCondition.condition is the model's payload and
    stays exported, so it is the surface for this regression. Export must refuse
    with nothing written."""
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    OtherCondition.objects.create(recipient=r, condition="onset 03/15/2020 per chart")
    with pytest.raises(CommandError):
        call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    assert not (tmp_path / "v0.1").exists()


def test_export_rejection_episode_columns_are_offsets(seeded_slice08, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "rejectionepisode.csv").open(newline="") as fh:
        row = list(csv.DictReader(fh))[0]
    assert row["recipient"] == "SCMVR07"
    assert row["rejection_type"] == "tcmr"
    assert row["banff_grade"] == "ia"
    assert row["biopsy_proven"] == "true"
    assert row["onset_day_offset"] == "120"  # 2025-05-01 is 120 days after kt
    assert row["biopsy_day_offset"] == "121"
    assert row["resolved_day_offset"] == "139"


def test_export_hospitalization_columns_are_offsets_and_los_derived(seeded_slice08, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "hospitalization.csv").open(newline="") as fh:
        row = list(csv.DictReader(fh))[0]
    assert row["recipient"] == "SCMVR07"
    assert row["admit_day_offset"] == "92"  # 2025-04-03 is 92 days after kt
    assert row["discharge_day_offset"] == "98"
    assert row["length_of_stay_days"] == "6"  # derived day-count
    assert row["disposition"] == "discharged_home"
    assert row["cmv_attribution"] != ""  # reviewer-set FK id present
    assert row["rejection_attribution"] != ""
    assert row["cmv_attributable"] == "true"


def test_export_hospitalization_reason_never_exported(seeded_slice08, tmp_path):
    """reason is free text -> a leak vector; disposition carries the signal."""
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for f in out.glob("*.csv"):
        text = f.read_text()
        assert "cmv viremia workup" not in text
    # reason is not even a column header anywhere
    with (out / "hospitalization.csv").open(newline="") as fh:
        assert "reason" not in csv.DictReader(fh).fieldnames


def test_export_manifest_lists_slice08_files(seeded_slice08, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    manifest = json.loads((out / "manifest.json").read_text())
    for name in ("medicationcourse.csv", "rejectionepisode.csv", "hospitalization.csv"):
        assert name in manifest["files"]
    assert manifest["files"]["medicationcourse.csv"]["columns"]["recipient"] == "c"


def test_export_slice08_leak_scan_over_new_files_and_columns(seeded_slice08, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for f in out.glob("*.csv"):
        text = f.read_text()
        assert "2025-01-01" not in text  # kt_date / course start never a calendar date
        assert "2025-03-02" not in text  # course end
        assert "2025-05-01" not in text  # rejection onset
        assert "2025-04-03" not in text  # admit date
        assert "2025-04-09" not in text  # discharge date
        assert "1980-01-01" not in text  # dob


def test_export_refuses_on_leaky_medication_agent(db, tmp_path):
    """A name-shaped value in an exported column (agent) triggers refusal with
    nothing written (the chokepoint stays intact)."""
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    c = MedicationCourse(
        recipient=r, drug_class="antiviral", dose_amount=Decimal("900"), dose_unit="mg",
        frequency="qd", course_type="prophylaxis", start_date=date(2025, 1, 1),
    )
    c.agent = "Maria Santos"  # name-shaped leak into an exported column
    c.save()  # bypass clean()
    with pytest.raises(CommandError):
        call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    assert not (tmp_path / "v0.1").exists()


# --- Slice 09: biobank ledger export (AC7) ---


@pytest.fixture
def seeded_slice09(db):
    """A visit-anchored aliquot with one thaw and two consumption events (one tied
    to a pipeline run), plus a sequencing transfer with a destruction certificate.
    The full Slice 09 export surface for the leak scan."""
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 15)
    )
    a = Aliquot.objects.create(
        recipient_visit=v, matrix="plasma", collected_date=date(2025, 1, 15),
        initial_volume_ul=Decimal("1000"),
    )
    ThawEvent.objects.create(aliquot=a, thawed_date=date(2025, 2, 1))
    ConsumptionEvent.objects.create(
        aliquot=a, volume_ul=Decimal("200"), consumed_date=date(2025, 2, 1)
    )
    ConsumptionEvent.objects.create(
        aliquot=a, volume_ul=Decimal("150"), consumed_date=date(2025, 2, 2)
    )
    SequencingAliquot.objects.create(
        aliquot=a, transfer_date=date(2025, 3, 1), destruction_certificate="MOA-2025-0042"
    )
    return r


def test_export_writes_aliquot_file(seeded_slice09, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    assert (tmp_path / "v0.1" / "aliquot.csv").exists()


def test_export_aliquot_materializes_derived_volume_and_thaw_count(seeded_slice09, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "aliquot.csv").open(newline="") as fh:
        row = list(csv.DictReader(fh))[0]
    assert row["recipient"] == "SCMVR07"  # FK key intact via the visit anchor
    assert row["matrix"] == "plasma"
    assert row["collected_day_offset"] == "14"  # 2025-01-15 is 14 days after kt
    assert row["initial_volume_ul"] == "1000.00"
    assert row["remaining_ul"] == "650.00"  # 1000 - (200 + 150), materialized derived
    assert row["thaw_count"] == "1"  # materialized derived


def test_export_aliquot_without_visit_blanks_offset_and_recipient(db, tmp_path):
    Aliquot.objects.create(
        matrix="serum", collected_date=date(2025, 1, 15), initial_volume_ul=Decimal("500")
    )
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "aliquot.csv").open(newline="") as fh:
        row = list(csv.DictReader(fh))[0]
    assert row["recipient"] == ""  # no visit anchor
    assert row["collected_day_offset"] == ""  # no kt anchor -> never a calendar date
    assert row["remaining_ul"] == "500.00"


def test_export_manifest_lists_aliquot_file(seeded_slice09, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    manifest = json.loads((out / "manifest.json").read_text())
    assert "aliquot.csv" in manifest["files"]
    assert manifest["files"]["aliquot.csv"]["columns"]["recipient"] == "c"


def test_export_destruction_certificate_never_exported(seeded_slice09, tmp_path):
    """The destruction certificate is free text -> a leak vector, never exported."""
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for f in out.glob("*.csv"):
        assert "MOA-2025-0042" not in f.read_text()


def test_export_slice09_leak_scan_over_new_files_and_columns(seeded_slice09, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for f in out.glob("*.csv"):
        text = f.read_text()
        assert "2025-01-15" not in text  # aliquot collected_date never a calendar date
        assert "2025-02-01" not in text  # thaw / consumption event dates
        assert "2025-03-01" not in text  # sequencing transfer_date
        assert "2025-01-01" not in text  # kt_date
        assert "1980-01-01" not in text  # dob


def test_export_refuses_on_leaky_aliquot_matrix(db, tmp_path):
    """A name-shaped value staged into an exported column (matrix) triggers refusal
    with nothing written (the chokepoint stays intact), bypassing clean()."""
    a = Aliquot(
        matrix="plasma", collected_date=date(2025, 1, 15), initial_volume_ul=Decimal("500")
    )
    a.matrix = "Maria Santos"  # name-shaped leak into an exported column
    a.save()  # bypass clean()
    with pytest.raises(CommandError):
        call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    assert not (tmp_path / "v0.1").exists()


# --- Slice 10: genotyping export (day-offsets only; no calendar date / identifier) ---


@pytest.fixture
def seeded_genotyping(db):
    """A visit-anchored aliquot with a Sanger genotyping result and two allele
    calls (a mixed gB1/gB3 infection), plus a SHA-pinned reference set — the full
    Slice 10 export surface for the leak scan."""
    editor = User.objects.create_user(username="bioinformatician")
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 15)
    )
    a = Aliquot.objects.create(
        recipient_visit=v, matrix="plasma", collected_date=date(2025, 1, 15),
        initial_volume_ul=Decimal("1000"),
    )
    run = PipelineRun.objects.create(
        input_manifest_sha256="a" * 64, started_at=date(2025, 2, 1), completed_at=date(2025, 2, 2)
    )
    res = GenotypingResult.objects.create(aliquot=a, pipeline_run=run, assay_type="sanger")
    GenotypeCall.objects.create(result=res, locus="gB", allele="gB1", sanger_call="R", entered_by=editor)
    GenotypeCall.objects.create(result=res, locus="gB", allele="gB3", sanger_call="R", entered_by=editor)
    return r


def test_export_writes_genotyping_files(seeded_genotyping, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    assert (out / "genotypingresult.csv").exists()
    assert (out / "genotypecall.csv").exists()


def test_export_genotyping_result_is_day_offset(seeded_genotyping, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "genotypingresult.csv").open(newline="") as fh:
        row = list(csv.DictReader(fh))[0]
    assert row["subject"] == "SCMVR07"  # opaque pseudonym only
    assert row["assay_type"] == "sanger"
    assert row["sample_day_offset"] == "14"  # 2025-01-15 is 14 days after kt day 0


def test_export_genotype_calls_are_long_one_row_per_allele(seeded_genotyping, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "genotypecall.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2  # mixed infection = two rows
    assert {r["allele"] for r in rows} == {"gB1", "gB3"}
    assert all(r["sanger_call"] == "R" for r in rows)


def test_export_genotyping_no_calendar_date_or_identifier(seeded_genotyping, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for f in out.glob("*.csv"):
        text = f.read_text()
        assert "2025-01-15" not in text  # sample date never a calendar date
        assert "2025-02-01" not in text  # pipeline started_at never leaves
        assert "2025-02-02" not in text  # pipeline completed_at never leaves
        assert "reviewer" not in text.lower()  # no staff-name columns
    gr = (out / "genotypingresult.csv").read_text()
    assert "sample_day_offset" in gr  # offsets, not dates
    assert "raw_ab1" not in gr and "sha256" not in gr  # no file SHAs / paths


def test_export_genotyping_manifest_lists_files(seeded_genotyping, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    manifest = json.loads((out / "manifest.json").read_text())
    assert "genotypingresult.csv" in manifest["files"]
    assert "genotypecall.csv" in manifest["files"]


def test_export_refuses_on_leaky_genotype_allele(db, tmp_path):
    """A name-shaped value in an exported genotype column triggers refusal with
    nothing written (the chokepoint stays intact)."""
    editor = User.objects.create_user(username="bioinformatician")
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 15)
    )
    a = Aliquot.objects.create(
        recipient_visit=v, matrix="plasma", collected_date=date(2025, 1, 15),
        initial_volume_ul=Decimal("1000"),
    )
    run = PipelineRun.objects.create(input_manifest_sha256="a" * 64)
    res = GenotypingResult.objects.create(aliquot=a, pipeline_run=run, assay_type="sanger")
    GenotypeCall.objects.create(result=res, locus="gB", allele="Maria Santos", entered_by=editor)
    with pytest.raises(CommandError):
        call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    assert not (tmp_path / "v0.1").exists()


# --- Slice 11: source attribution + genotype concordance export (AC5, AC6) ---


def _geno_result_for(recipient, calls, tag):
    """A GenotypingResult anchored (through the tube) to `recipient`, carrying the
    given (locus, allele, sanger_call) calls. `tag` keeps usernames/SHAs unique."""
    editor = User.objects.create_user(username=f"bio-{tag}")
    v = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_7", actual_visit_date=date(2025, 1, 15)
    )
    a = Aliquot.objects.create(
        recipient_visit=v, matrix="plasma", collected_date=date(2025, 1, 15),
        initial_volume_ul=Decimal("1000"),
    )
    run = PipelineRun.objects.create(input_manifest_sha256=(tag * 64)[:64])
    res = GenotypingResult.objects.create(aliquot=a, pipeline_run=run, assay_type="sanger")
    for locus, allele, sc in calls:
        GenotypeCall.objects.create(
            result=res, locus=locus, allele=allele, sanger_call=sc, entered_by=editor
        )
    return res


@pytest.fixture
def seeded_slice11(db):
    """A confirmed donor-derived superinfection pair: a recipient with two
    sequenced strains compared across a hypervariable (gN), a conserved (gB), and
    a resistance (UL97) locus. The full Slice 11 export surface."""
    reviewer = User.objects.create_user(username="adjudicator")
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=date(2025, 1, 1), donor_serostatus="POS", recipient_serostatus="NEG",
    )
    rec_res = _geno_result_for(
        r, [("gN", "gN1", "R"), ("gB", "gB1", "R"), ("UL97", "wt", "R")], "1"
    )
    comp_res = _geno_result_for(r, [("gN", "gN1", "R"), ("gB", "gB1", "R")], "2")
    ConcordancePair.objects.create(
        recipient=r, recipient_result=rec_res, comparator_result=comp_res,
        concordance_call="concordant", superinfection_status="confirmed",
        reviewed_by=reviewer, reviewed_at=date(2025, 4, 1),
    )
    return r


def test_export_writes_concordance_files(seeded_slice11, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    assert (out / "concordancepair.csv").exists()
    assert (out / "concordancelocus.csv").exists()


def test_export_concordance_pair_summary_is_de_identified(seeded_slice11, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "concordancepair.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    row = rows[0]
    assert row["recipient"] == "SCMVR07"  # pseudonym, not a real identity
    assert row["concordance_call"] == "concordant"  # reviewer-set
    assert row["suggested_concordance_call"] == "concordant"  # derived from the calls
    assert row["co_resolved_count"] == "2"  # gN + gB; UL97 excluded
    assert row["superinfection_status"] == "confirmed"
    # no staff-name columns leak
    assert "reviewed_by" not in row
    assert "reviewed_at" not in row


def test_export_concordance_locus_table_orders_and_labels_resistance(seeded_slice11, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "concordancelocus.csv").open(newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["locus"]]  # drop blank separator row
    loci = [r["locus"] for r in rows]
    assert loci == ["gN", "gB", "UL97"]  # hypervariable -> conserved -> resistance-last
    by_locus = {r["locus"]: r for r in rows}
    # resistance locus carries the literal label and is not counted for strain identity
    assert by_locus["UL97"]["strain_identity_note"] == "not counted for strain identity"
    assert by_locus["UL97"]["counted_for_strain_identity"] == "false"
    # strain-identity loci carry no note
    assert by_locus["gN"]["strain_identity_note"] == ""
    assert by_locus["gB"]["counted_for_strain_identity"] == "true"
    # alleles are present and the recipient key is intact
    assert by_locus["gN"]["allele_recipient"] == "gN1"
    assert all(r["recipient"] == "SCMVR07" for r in rows)


def test_export_concordance_locus_table_visually_separates_resistance(seeded_slice11, tmp_path):
    """A blank separator row precedes the resistance block (AC5 'visually separated')."""
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "concordancelocus.csv").open(newline="") as fh:
        raw = list(csv.reader(fh))
    # header + gN + gB + blank + UL97
    blank_idx = [i for i, row in enumerate(raw) if row == []]
    assert blank_idx  # at least one separator row
    # the row immediately after the last separator is a resistance locus
    after = raw[blank_idx[-1] + 1]
    assert after[raw[0].index("locus")] == "UL97"


def test_export_recipient_has_source_label(seeded_slice11, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "recipient.csv").open(newline="") as fh:
        row = list(csv.DictReader(fh))[0]
    assert "source_label" in row
    # a confirmed superinfection upgrades the source label to donor_derived (AC1/AC6)
    assert row["source_label"] == "donor_derived"


def test_export_recipient_source_label_blank_when_none(seeded, tmp_path):
    """No attributable CMV event -> source_label is blank, not a fabricated value."""
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "recipient.csv").open(newline="") as fh:
        row = list(csv.DictReader(fh))[0]
    assert row["source_label"] == ""


def test_export_manifest_lists_concordance_files(seeded_slice11, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    manifest = json.loads((out / "manifest.json").read_text())
    assert "concordancepair.csv" in manifest["files"]
    assert "concordancelocus.csv" in manifest["files"]
    assert manifest["files"]["concordancepair.csv"]["columns"]["recipient"] == "c"
    assert manifest["files"]["concordancelocus.csv"]["columns"]["locus"] == "c"


def test_export_slice11_leak_scan_over_concordance_files(seeded_slice11, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for f in out.glob("*.csv"):
        text = f.read_text()
        assert "2025-04-01" not in text  # reviewed_at never a calendar date
        assert "adjudicator" not in text  # reviewer staff name never exported
        assert "1980-01-01" not in text  # dob


def test_export_refuses_on_leaky_concordance_allele(db, tmp_path):
    """A name-shaped allele flows into concordancelocus.csv; the de-id chokepoint
    must refuse with nothing written (mirrors the genotypecall case)."""
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    rec_res = _geno_result_for(r, [("gB", "Maria Santos", "R")], "1")
    ConcordancePair.objects.create(recipient=r, recipient_result=rec_res)
    with pytest.raises(CommandError):
        call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    assert not (tmp_path / "v0.1").exists()


# --- Slice 12: resistance surveillance export (AC4) — kept SEPARATE from the
# strain-identity loci, day-offsets only, no calendar date / identifier. ---


@pytest.fixture
def seeded_slice12(db):
    """A recipient with two resistance calls riding the same tube→result chain as
    genotyping: an actionable UL97 call (established variant + active virological
    failure -> return-of-results flag) and a UL54 polymorphism call without active
    failure. The derived sample_date (2025-04-01, day 90) must leave only as a
    day-offset integer."""
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_90", actual_visit_date=date(2025, 4, 1)
    )
    a = Aliquot.objects.create(
        recipient_visit=v, matrix="plasma", collected_date=date(2025, 4, 1),
        initial_volume_ul=Decimal("1000"),
    )
    run = PipelineRun.objects.create(input_manifest_sha256="a" * 64)
    res = GenotypingResult.objects.create(aliquot=a, pipeline_run=run, assay_type="sanger")
    ul97 = ResistanceCall.objects.create(
        result=res, locus="UL97", status="R", qnat_iu_ml=Decimal("1500")
    )
    ResistanceVariant.objects.create(resistance_call=ul97, variant="C592G", tier="established")
    ul54 = ResistanceCall.objects.create(
        result=res, locus="UL54", status="F", qnat_iu_ml=Decimal("10")
    )
    ResistanceVariant.objects.create(resistance_call=ul54, variant="M460V", tier="polymorphism")
    return r


def test_export_writes_resistance_files(seeded_slice12, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    assert (out / "resistancecall.csv").exists()
    assert (out / "resistancevariant.csv").exists()


def test_export_resistance_call_is_de_identified_day_offset(seeded_slice12, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "resistancecall.csv").open(newline="") as fh:
        rows = {r["locus"]: r for r in csv.DictReader(fh)}
    assert set(rows) == {"UL97", "UL54"}
    ul97 = rows["UL97"]
    assert ul97["subject"] == "SCMVR07"  # opaque pseudonym only
    assert ul97["status"] == "R"
    assert ul97["established_resistance_present"] == "true"
    assert ul97["return_of_results_flag"] == "true"  # established ∩ active failure
    assert ul97["qnat_iu_ml"] == "1500.00"  # a value, never a date
    assert ul97["sample_day_offset"] == "90"  # 2025-04-01 is 90 days after kt day 0
    # established without active failure does not raise the flag
    assert rows["UL54"]["established_resistance_present"] == "false"
    assert rows["UL54"]["return_of_results_flag"] == "false"


def test_export_resistance_variants_are_long_one_row_per_variant(seeded_slice12, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "resistancevariant.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert {(r["variant"], r["tier"]) for r in rows} == {
        ("C592G", "established"),
        ("M460V", "polymorphism"),
    }


def test_export_resistance_kept_separate_from_strain_identity_loci(seeded_slice12, tmp_path):
    """AC4: resistance surveillance loci live in their OWN file, never folded into
    the strain-identity concordance locus table."""
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    # no concordance pair seeded here -> the strain-identity locus table has no rows
    with (out / "concordancelocus.csv").open(newline="") as fh:
        assert [r for r in csv.DictReader(fh) if r["locus"]] == []
    # but the resistance call file carries the UL97/UL54 surveillance calls
    with (out / "resistancecall.csv").open(newline="") as fh:
        loci = {r["locus"] for r in csv.DictReader(fh)}
    assert loci == {"UL97", "UL54"}


def test_export_resistance_no_calendar_date_or_identifier(seeded_slice12, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for f in out.glob("*.csv"):
        text = f.read_text()
        assert "2025-04-01" not in text  # sample/collection date never a calendar date
        assert "1980-01-01" not in text  # dob
    rc = (out / "resistancecall.csv").read_text()
    assert "sample_day_offset" in rc  # offsets, not dates


def test_export_manifest_lists_resistance_files(seeded_slice12, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    manifest = json.loads((out / "manifest.json").read_text())
    assert "resistancecall.csv" in manifest["files"]
    assert "resistancevariant.csv" in manifest["files"]
    assert manifest["files"]["resistancecall.csv"]["columns"]["subject"] == "c"
    assert manifest["files"]["resistancecall.csv"]["columns"]["sample_day_offset"] == "i"
    assert manifest["files"]["resistancevariant.csv"]["columns"]["tier"] == "c"


def test_export_refuses_on_leaky_resistance_variant(db, tmp_path):
    """A name-shaped value planted in an exported resistance column triggers the
    de-id chokepoint with nothing written (mirrors the genotypecall case)."""
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_90", actual_visit_date=date(2025, 4, 1)
    )
    a = Aliquot.objects.create(
        recipient_visit=v, matrix="plasma", collected_date=date(2025, 4, 1),
        initial_volume_ul=Decimal("1000"),
    )
    run = PipelineRun.objects.create(input_manifest_sha256="a" * 64)
    res = GenotypingResult.objects.create(aliquot=a, pipeline_run=run, assay_type="sanger")
    call = ResistanceCall.objects.create(result=res, locus="UL97", status="R")
    ResistanceVariant.objects.create(
        resistance_call=call, variant="Maria Santos", tier="established"
    )
    with pytest.raises(CommandError):
        call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    assert not (tmp_path / "v0.1").exists()
    assert list(tmp_path.glob(".v0.1.staging-*")) == []


# --- Slice 14: safety release-timeliness export (AC5) — day-offsets only, the
# dual-track deviation/SAE facts, no calendar date / identifier / free text. ---


@pytest.fixture
def seeded_slice14(db):
    """A recipient with a high-viral-load reported QNAT (drawn day 90), a logged
    ReleaseEvent (released day 92), and a dual-track ProtocolDeviation recorded at
    day 95. Every date must leave only as an integer day-offset from kt_date."""
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_90", actual_visit_date=date(2025, 4, 1)
    )
    q = CMVQuantitative.objects.create(
        recipient_visit=v, value=Decimal("15000"), result_status="reported",
        severity_tier="disease", drawn_date=date(2025, 4, 1),
    )
    ReleaseEvent.objects.create(quantitative=q, released_date=date(2025, 4, 3))  # day 92
    ProtocolDeviation.objects.create(
        quantitative=q, deviation_type="late_release", caused_harm=True,
        is_research_related_sae=True, recorded_date=date(2025, 4, 6),  # day 95
    )
    return r


def test_export_writes_safety_files(seeded_slice14, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    assert (out / "releaseevent.csv").exists()
    assert (out / "protocoldeviation.csv").exists()


def test_export_release_event_is_day_offset(seeded_slice14, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "releaseevent.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    row = rows[0]
    assert row["recipient"] == "SCMVR07"  # opaque pseudonym only
    assert row["released_day_offset"] == "92"  # 2025-04-03 is 92 days after kt day 0
    assert "released_date" not in row  # the raw DateField never becomes a column


def test_export_protocol_deviation_is_dual_track_day_offset(seeded_slice14, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "protocoldeviation.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    row = rows[0]
    assert row["recipient"] == "SCMVR07"
    assert row["deviation_type"] == "late_release"
    assert row["caused_harm"] == "true"
    assert row["is_research_related_sae"] == "true"  # dual-track, both countable
    assert row["recorded_day_offset"] == "95"
    assert "recorded_date" not in row


def test_export_safety_no_calendar_date_or_identifier(seeded_slice14, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for f in (out / "releaseevent.csv", out / "protocoldeviation.csv"):
        text = f.read_text()
        for rx in (DATE_RX, NAME_RX, MRN_RX, ADDRESS_RX):
            assert rx.search(text) is None  # day-offsets only, no identifier shapes
        assert "2025-04-01" not in text  # no calendar date
        assert "1980-01-01" not in text  # no dob


def test_export_safety_files_have_no_free_text_column(seeded_slice14, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    for name in ("releaseevent.csv", "protocoldeviation.csv"):
        with (out / name).open(newline="") as fh:
            header = next(csv.reader(fh))
        # only structured columns; no note/reason/comment free-text leak vector
        assert not any(
            k in h for h in header for k in ("note", "reason", "comment", "_date")
        )


def test_export_manifest_lists_safety_files(seeded_slice14, tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    manifest = json.loads((out / "manifest.json").read_text())
    assert "releaseevent.csv" in manifest["files"]
    assert "protocoldeviation.csv" in manifest["files"]
    assert manifest["files"]["releaseevent.csv"]["columns"]["released_day_offset"] == "i"
    assert manifest["files"]["releaseevent.csv"]["row_count"] == 1
    assert manifest["files"]["protocoldeviation.csv"]["columns"]["recorded_day_offset"] == "i"
    assert manifest["files"]["protocoldeviation.csv"]["columns"]["deviation_type"] == "c"
    assert "sha256" in manifest["files"]["protocoldeviation.csv"]


def test_export_safety_donor_attached_qnat_blanks_offset(db, tmp_path):
    """A release-event on a donor-attached QNAT has no kt anchor -> blank offset,
    never the calendar released_date (the donor/DonorVisit precedent)."""
    d = Donor.objects.create(
        subject_id="DCMVD07", date_of_birth=date(1980, 1, 1), sex="M", donor_type="living"
    )
    q = CMVQuantitative.objects.create(
        donor=d, value=Decimal("99999"), result_status="reported", drawn_date=date(2025, 4, 1)
    )
    ReleaseEvent.objects.create(quantitative=q, released_date=date(2025, 4, 1))
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "releaseevent.csv").open(newline="") as fh:
        row = next(csv.DictReader(fh))
    assert row["recipient"] == ""
    assert row["released_day_offset"] == ""


def test_export_refuses_on_leaky_deviation_type(db, tmp_path):
    """A name-shaped value planted in an exported safety column triggers the de-id
    chokepoint with nothing written (mirrors the leaky closure_reason case)."""
    r = Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_90", actual_visit_date=date(2025, 4, 1)
    )
    q = CMVQuantitative.objects.create(
        recipient_visit=v, value=Decimal("15000"), result_status="reported",
        drawn_date=date(2025, 4, 1),
    )
    # .save() bypasses clean()/choices to plant a leaky value into an exported column.
    ProtocolDeviation.objects.create(quantitative=q, deviation_type="Maria Santos")
    with pytest.raises(CommandError):
        call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    assert not (tmp_path / "v0.1").exists()
    assert list(tmp_path.glob(".v0.1.staging-*")) == []
