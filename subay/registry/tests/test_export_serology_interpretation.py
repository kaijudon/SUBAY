"""Slice 17, ticket 04 - the frozen snapshot carries the serology interpretation.

The export is the only surface an R analyst ever sees, and until this ticket it
published two positivity booleans against a single 2.0 AU/mL cutoff. That cutoff
stopped being the whole rule on 2026-06-03 (DEC-030): the two channels diverged,
and both gained a grayzone. A boolean cannot say "equivocal", so it rounded an
indeterminate reading into a clean answer the lab never gave.

What replaces it: a three-state interpretation per channel, plus the reagent
generation that produced the row, so the file is readable without anyone having
to ask which reagent was in force on a given date. The raw measured values stay
so the analyst can re-band independently of whatever SUBAY decided.
"""
import csv
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command

from subay.registry.management.commands.export_analysis_set import SEROLOGY_COLUMNS
from subay.registry.models import CMVSerology, Recipient, RecipientVisit
from subay.registry.serology_ranges import (
    ADVISORY_EFFECTIVE,
    GEN1,
    GEN2,
    GEN2_IGG_EQUIVOCAL_FROM_AU_ML,
    GEN2_IGM_EQUIVOCAL_FROM_AU_ML,
)


@pytest.fixture
def seeded_both_generations(db):
    """Two recipients whose serology straddles the advisory boundary.

    SCMVR01 was drawn the day before the advisory: 1st-generation reagent, one
    cutoff, no grayzone. SCMVR02 was drawn the day of it: 2nd-generation bands,
    and both of its channels land in the new equivocal window - which is the
    case the old boolean columns could not express at all.

    SCMVR02's IgM is measured and equivocal; SCMVR01's IgM is not measured at
    all. The pair is what makes "equivocal" and "blank" separable in one file.
    """
    before = ADVISORY_EFFECTIVE - timedelta(days=1)

    r1 = Recipient.objects.create(
        subject_id="SCMVR01", date_of_birth=date(1980, 1, 1), sex="M", kt_date=before
    )
    v1 = RecipientVisit.objects.create(
        recipient=r1, timepoint_label="pre_kt", actual_visit_date=before
    )
    CMVSerology.objects.create(
        recipient_visit=v1,
        value=Decimal("3.00"),  # >= 2.00 -> reactive on 1st generation
        drawn_date=before,  # IgM left unmeasured
    )

    r2 = Recipient.objects.create(
        subject_id="SCMVR02",
        date_of_birth=date(1981, 2, 2),
        sex="F",
        kt_date=ADVISORY_EFFECTIVE,
    )
    v2 = RecipientVisit.objects.create(
        recipient=r2, timepoint_label="pre_kt", actual_visit_date=ADVISORY_EFFECTIVE
    )
    CMVSerology.objects.create(
        recipient_visit=v2,
        value=GEN2_IGG_EQUIVOCAL_FROM_AU_ML,  # at the lower edge -> equivocal
        igm_value=GEN2_IGM_EQUIVOCAL_FROM_AU_ML,  # at the lower edge -> equivocal
        igm_status="reported",
        drawn_date=ADVISORY_EFFECTIVE,
    )
    return r1, r2


def _serology_rows(tmp_path):
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    out = tmp_path / "v0.1"
    with (out / "cmvserology.csv").open(newline="") as fh:
        rows = {r["parent_id"]: r for r in csv.DictReader(fh)}
    return out, rows


def _by_subject(rows, recipients):
    """Key the exported rows by subject_id. The CSV carries the visit's pk in
    parent_id, so this walks the visit back to its recipient rather than
    assuming an autoincrement order the test does not control."""
    return {
        r.subject_id: rows[str(r.visits.get().pk)] for r in recipients
    }


def test_export_replaces_positivity_booleans_with_interpretations():
    """The two boolean columns are gone from the contract, not merely unused.

    Ticket 04 is a caller migration inside an expand-contract sequence: the
    PROPERTIES stay (ticket 07 retires those), but nothing in the frozen
    snapshot may still publish a positivity boolean, because a boolean is the
    exact shape that cannot carry the grayzone.
    """
    names = [name for name, _ in SEROLOGY_COLUMNS]
    assert "is_positive" not in names
    assert "igm_positive" not in names
    assert "igg_interpretation" in names
    assert "igm_interpretation" in names


def test_export_withholds_the_reagent_generation(seeded_both_generations, tmp_path):
    """The generation is a date in disguise and must not reach the snapshot.

    generation_for() returns gen2 exactly when the draw fell on or after the
    2026-06-03 advisory, so the code partitions every row by a known calendar
    boundary. Next to day_offset that narrows the transplant date to a window,
    which is the disclosure the day-offset rule exists to prevent. The column
    passes _assert_no_identifier_leak untouched - "gen2" is not date-shaped -
    so nothing but this test stands between it and the file.
    """
    _, rows = _serology_rows(tmp_path)

    assert "reagent_generation" not in [name for name, _ in SEROLOGY_COLUMNS]
    for row in rows.values():
        assert "reagent_generation" not in row
        assert GEN1 not in row.values()
        assert GEN2 not in row.values()


def test_export_reads_each_row_against_its_own_generation(seeded_both_generations, tmp_path):
    """The same file holds both interpretations at once without either
    corrupting the other. 3.00 AU/mL is reactive under the 1st-generation
    cutoff; 0.80 AU/mL is equivocal only because its row is 2nd generation.

    With the generation column withheld this is the only remaining evidence that
    per-row banding happened at all, so it carries more weight than it did when
    the analyst could read the generation off the file and check the work.
    """
    _, rows = _serology_rows(tmp_path)
    by_subject = _by_subject(rows, seeded_both_generations)

    assert by_subject["SCMVR01"]["igg_interpretation"] == "reactive"
    assert by_subject["SCMVR02"]["igg_interpretation"] == "equivocal"
    assert by_subject["SCMVR02"]["igm_interpretation"] == "equivocal"


def test_export_distinguishes_equivocal_from_not_measured(seeded_both_generations, tmp_path):
    """The defect this ticket exists to close.

    Blank means "no observation was obtained" and nothing else. An equivocal
    reading is an observation - a real, indeterminate one - and must occupy the
    column as its own value. If both collapsed to blank, an analyst counting
    non-missing IgM results would silently drop every grayzone draw.
    """
    _, rows = _serology_rows(tmp_path)
    by_subject = _by_subject(rows, seeded_both_generations)

    assert by_subject["SCMVR01"]["igm_status"] == "missing"
    assert by_subject["SCMVR01"]["igm_interpretation"] == ""  # not measured
    assert by_subject["SCMVR02"]["igm_status"] == "reported"
    assert by_subject["SCMVR02"]["igm_interpretation"] == "equivocal"  # measured


def test_export_still_carries_the_raw_measured_values(seeded_both_generations, tmp_path):
    """SUBAY's banding is an interpretation, not the observation. The analyst
    keeps the numbers so the SAP can re-derive or re-band without trusting the
    app's reading."""
    _, rows = _serology_rows(tmp_path)
    by_subject = _by_subject(rows, seeded_both_generations)

    assert by_subject["SCMVR01"]["value"] == "3.00"
    assert by_subject["SCMVR02"]["value"] == "0.80"
    assert by_subject["SCMVR02"]["igm_value"] == "2.00"


def test_export_adds_no_calendar_date_shaped_column():
    """The day-offset contract is untouched. Nothing this ticket adds is of
    `drawn_date` shape, and the only date-derived column stays day_offset."""
    names = [name for name, _ in SEROLOGY_COLUMNS]
    assert not [n for n in names if "date" in n]
    assert "day_offset" in names


def test_export_leak_scan_over_the_new_serology_columns(seeded_both_generations, tmp_path):
    """Every data slice widens leak coverage rather than deferring it. The two
    calendar dates that could reach this file are the draw dates, and both
    straddle the advisory, so the sweep pins both sides of the boundary."""
    out, _ = _serology_rows(tmp_path)
    before = (ADVISORY_EFFECTIVE - timedelta(days=1)).isoformat()

    for f in out.glob("*.csv"):
        text = f.read_text()
        assert ADVISORY_EFFECTIVE.isoformat() not in text  # gen2 drawn_date / kt_date
        assert before not in text  # gen1 drawn_date / kt_date
        assert "1980-01-01" not in text  # dob
        assert "1981-02-02" not in text  # dob


def test_export_manifest_declares_the_new_serology_column_types(
    seeded_both_generations, tmp_path
):
    """The manifest is the machine-readable contract R reads the file against;
    a column present in the CSV but absent from the manifest is a silent
    schema drift."""
    out, _ = _serology_rows(tmp_path)
    columns = json.loads((out / "manifest.json").read_text())["files"]["cmvserology.csv"][
        "columns"
    ]

    assert "reagent_generation" not in columns
    assert columns["igg_interpretation"] == "c"
    assert columns["igm_interpretation"] == "c"
    assert "is_positive" not in columns
    assert "igm_positive" not in columns


def test_export_serology_checksum_is_reproducible(seeded_both_generations, tmp_path):
    """Unchanged database state must still produce a byte-identical file. The
    new columns are derived at write time, so a nondeterministic one (dict
    ordering, a set, a timestamp) would break the frozen-snapshot guarantee
    without breaking any assertion above."""
    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    call_command("export_analysis_set", "v0.2", outdir=str(tmp_path))

    first = json.loads((tmp_path / "v0.1" / "manifest.json").read_text())
    second = json.loads((tmp_path / "v0.2" / "manifest.json").read_text())
    assert (
        first["files"]["cmvserology.csv"]["sha256"]
        == second["files"]["cmvserology.csv"]["sha256"]
    )


def test_positivity_booleans_survive_this_ticket():
    """Expand-contract guard rail. Ticket 04 migrates a caller; retiring the
    properties is ticket 07's job, and doing it early would break the tickets
    that have not been migrated yet."""
    assert isinstance(CMVSerology.is_positive, property)
    assert isinstance(CMVSerology.igm_positive, property)
