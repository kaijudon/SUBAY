"""Slice 17 - CMV serology reference ranges, per reagent generation.

The SPMC Transplant Immunology Unit moved to second-generation assay reagents on
3 June 2026 and issued new reference values with immediate effect. A result is
readable only against the ranges that were in force when the sample was run, so
every row carries its reagent generation and is interpreted against that
generation's bands (DEC-030 decision 2).

Both channels and both generations are AU/mL. The advisory's CMV IgG row reads
"IU/mL"; that is a transcription error, confirmed with the lab on 2026-08-04
(DEC-032). There is no unit change and no stored value is ever rescaled.
"""
import importlib
from datetime import date, timedelta
from decimal import Decimal

import pytest

from subay.registry.serology_ranges import (
    ADVISORY_EFFECTIVE,
    EQUIVOCAL,
    GEN1,
    GEN2,
    NON_REACTIVE,
    REACTIVE,
    generation_for,
    interpret_igg,
    interpret_igm,
)


@pytest.mark.parametrize(
    "drawn,expected",
    [
        (date(2026, 6, 2), GEN1),  # day before the advisory
        (date(2026, 6, 3), GEN2),  # the advisory took effect ON this day
        (date(2026, 6, 4), GEN2),
        (date(2020, 1, 1), GEN1),  # long before
        (date(2030, 1, 1), GEN2),  # long after
    ],
)
def test_generation_follows_the_advisory_date(drawn, expected):
    """The boundary is INCLUSIVE: a draw on 3 June 2026 is second generation.

    This is the whole rule the migration's backfill applies, tested here rather
    than through a migration harness, so the migration has no logic of its own
    to get wrong.
    """
    assert generation_for(drawn) == expected


# ------------------------------------------------------------------ the bands
#
# Every boundary below is INCLUSIVE at the lower edge and EXCLUSIVE at the upper,
# so each is tested at the boundary value itself and on both sides of it. Getting
# one of these the wrong way round is the single most likely defect on this card,
# and it would be invisible: the result would still be a plausible-looking answer.


@pytest.mark.parametrize(
    "value,expected",
    [
        (Decimal("1.99"), NON_REACTIVE),
        (Decimal("2.00"), REACTIVE),  # at cutoff -> reactive (DEC-016)
        (Decimal("2.01"), REACTIVE),
        (Decimal("0"), NON_REACTIVE),
        (None, None),  # not measured
    ],
)
def test_first_generation_has_a_single_cutoff_and_no_equivocal_band(value, expected):
    """Frozen rows keep the DEC-016 reading: one shared cutoff, two answers.

    Both channels behaved identically before the advisory, which is why one
    constant could serve them both. Pre-advisory rows are never re-interpreted
    (DEC-030 decision 2), so this rule has to keep working forever.
    """
    assert interpret_igg(value, GEN1) == expected
    assert interpret_igm(value, GEN1) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (Decimal("0.79"), NON_REACTIVE),
        (Decimal("0.80"), EQUIVOCAL),  # grayzone opens here
        (Decimal("1.19"), EQUIVOCAL),
        (Decimal("1.20"), REACTIVE),  # grayzone closes here
        (Decimal("5.00"), REACTIVE),
        (None, None),
    ],
)
def test_second_generation_igg_bands(value, expected):
    assert interpret_igg(value, GEN2) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (Decimal("1.99"), NON_REACTIVE),
        (Decimal("2.00"), EQUIVOCAL),  # grayzone opens here
        (Decimal("4.19"), EQUIVOCAL),
        (Decimal("4.20"), REACTIVE),  # grayzone closes here
        (Decimal("9.00"), REACTIVE),
        (None, None),
    ],
)
def test_second_generation_igm_bands(value, expected):
    assert interpret_igm(value, GEN2) == expected


def test_the_two_channels_diverged_at_the_second_generation():
    """One shared threshold can no longer express the rule, which is the reason
    the constant is being split rather than merely retuned.

    2.00 AU/mL reads reactive on IgG and equivocal on IgM under the new ranges.
    A single shared constant cannot produce both answers.
    """
    assert interpret_igg(Decimal("2.00"), GEN2) == REACTIVE
    assert interpret_igm(Decimal("2.00"), GEN2) == EQUIVOCAL


# ----------------------------------------------------- the model carries them


@pytest.fixture
def visit(db):
    from subay.registry.models import Recipient, RecipientVisit

    r = Recipient.objects.create(
        subject_id="SCMVR01", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2026, 1, 1)
    )
    return RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2026, 1, 8)
    )


@pytest.mark.django_db
def test_reagent_generation_is_stored_not_derived(visit):
    """Stored on purpose. If it were derived from drawn_date, then correcting a
    mistyped draw date would silently re-interpret a frozen clinical reading -
    the exact failure DEC-030 decision 2 exists to prevent."""
    from subay.registry.models import CMVSerology

    field_names = {f.name for f in CMVSerology._meta.get_fields()}
    assert "reagent_generation" in field_names


@pytest.mark.django_db
def test_a_new_row_defaults_its_generation_from_the_draw_date(visit):
    from subay.registry.models import CMVSerology

    before = CMVSerology.objects.create(
        recipient_visit=visit, value=Decimal("1.50"), drawn_date=date(2026, 6, 2)
    )
    on_the_day = CMVSerology.objects.create(
        recipient_visit=visit, value=Decimal("1.50"), drawn_date=date(2026, 6, 3)
    )
    assert before.reagent_generation == GEN1
    assert on_the_day.reagent_generation == GEN2


@pytest.mark.django_db
def test_a_late_entered_result_can_override_the_generation(visit):
    """A sample run on first-generation reagent whose result only reaches the
    register now. The draw date cannot express this; the stored field can."""
    from subay.registry.models import CMVSerology

    s = CMVSerology.objects.create(
        recipient_visit=visit,
        value=Decimal("1.50"),
        drawn_date=date(2026, 7, 1),
        reagent_generation=GEN1,
    )
    s.refresh_from_db()
    assert s.reagent_generation == GEN1


@pytest.mark.django_db
def test_the_same_number_reads_differently_either_side_of_the_advisory(visit):
    """The defect this whole card exists to fix.

    1.50 AU/mL is non-reactive under the first-generation single cutoff of 2.00
    and reactive under the second-generation IgG boundary of 1.20. Both readings
    are correct for their own reagent. Neither row is ever re-interpreted.
    """
    from subay.registry.models import CMVSerology

    frozen = CMVSerology.objects.create(
        recipient_visit=visit, value=Decimal("1.50"), drawn_date=date(2026, 6, 2)
    )
    current = CMVSerology.objects.create(
        recipient_visit=visit, value=Decimal("1.50"), drawn_date=date(2026, 6, 3)
    )
    assert frozen.igg_interpretation == NON_REACTIVE
    assert current.igg_interpretation == REACTIVE


@pytest.mark.django_db
def test_both_channels_are_interpreted_against_the_rows_own_generation(visit):
    from subay.registry.models import CMVSerology

    s = CMVSerology.objects.create(
        recipient_visit=visit,
        value=Decimal("1.00"),      # gen2 IgG: equivocal (0.80 to <1.20)
        igm_value=Decimal("3.00"),  # gen2 IgM: equivocal (2.00 to <4.20)
        igm_status="reported",
        drawn_date=date(2026, 7, 1),
    )
    assert s.reagent_generation == GEN2
    assert s.igg_interpretation == EQUIVOCAL
    assert s.igm_interpretation == EQUIVOCAL


@pytest.mark.django_db
def test_an_unmeasured_channel_has_no_interpretation(visit):
    """None is not a fourth clinical answer. It mirrors result_status='missing':
    a QC or lab failure means no observation was obtained at all."""
    from subay.registry.models import CMVSerology

    s = CMVSerology.objects.create(
        recipient_visit=visit, value=Decimal("5.00"), drawn_date=date(2026, 7, 1)
    )
    assert s.igg_interpretation == REACTIVE
    assert s.igm_interpretation is None  # igm_status defaults to 'missing'


def test_the_0020_backfill_still_agrees_with_the_live_rule():
    """Migration 0020 copies the 2026-06-03 boundary instead of importing it.

    The copy is deliberate: a migration that imports live app code stops applying
    the day that code is renamed, and a migration that FOLLOWS a corrected
    boundary would hand a fresh database different stamps than production already
    carries. Both make the copy right and the drift the only real risk, so the
    drift is what gets asserted - here, at test time, rather than by coupling the
    two at migrate time.

    Loaded by path because the module name starts with a digit.
    """
    m = importlib.import_module("subay.registry.migrations.0020_slice17_reagent_generation")

    assert m.ADVISORY_EFFECTIVE == ADVISORY_EFFECTIVE
    assert (m.GEN1, m.GEN2) == (GEN1, GEN2)
    # The boundary day itself and both sides of it: an off-by-one in either
    # direction is what a date constant drifts into.
    for offset in (-1, 0, 1):
        day = ADVISORY_EFFECTIVE + timedelta(days=offset)
        assert m._generation_for(day) == generation_for(day), day
