"""Slice 17 ticket 02 - an equivocal IgG stops being rounded into an answer.

The second-generation reagent opened a grayzone on both channels. A subject
whose IgG lands in it has no established serostatus: the PI's ruling is that the
grayzone is not a category, so an equivocal recipient sits in the undetermined
bucket until a repeat draw resolves it, exactly as though the draw were missing.

A donor has at most one baseline serology, so an equivocal donor result is
terminal instead. The consequence there is on the reconciliation flag, which
answered "no mismatch" whenever it could not compare - presenting the weakest
possible donor evidence to a reviewer as a clean all-clear.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from subay.registry.models import CMVSerology, Donor, Recipient, RecipientVisit
from subay.registry.serology_ranges import (
    EQUIVOCAL,
    NEG,
    NON_REACTIVE,
    POS,
    REACTIVE,
    serostatus_from,
)

# Both draws below are second generation (on or after 2026-06-03), so the IgG
# bands are non-reactive <0.80, equivocal 0.80 to <1.20, reactive >=1.20 AU/mL.
GEN2_DRAW = date(2026, 7, 1)


@pytest.mark.parametrize(
    "interpretation,expected",
    [
        (REACTIVE, POS),
        (NON_REACTIVE, NEG),
        (EQUIVOCAL, None),  # a grayzone, not a third category
        (None, None),       # not measured
    ],
)
def test_serostatus_translation_is_written_once(interpretation, expected):
    """The recipient and donor derivations both call this, so they cannot drift
    apart on what an equivocal reading means."""
    assert serostatus_from(interpretation) == expected


def _recipient(subject_id="SCMVR01", **kw):
    return Recipient.objects.create(
        subject_id=subject_id,
        date_of_birth=date(1980, 1, 1),
        sex="M",
        kt_date=date(2026, 8, 1),
        **kw,
    )


def _pre_kt_igg(recipient, value):
    visit = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="pre_kt", actual_visit_date=GEN2_DRAW
    )
    return CMVSerology.objects.create(
        recipient_visit=visit, value=Decimal(value), drawn_date=GEN2_DRAW
    )


def _donor(subject_id="DCMVD01"):
    return Donor.objects.create(
        subject_id=subject_id, date_of_birth=date(1975, 1, 1), sex="F"
    )


# --- The recipient's pre-transplant serostatus -----------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "value,expected",
    [
        ("1.50", POS),   # reactive under the second-generation IgG range
        ("0.50", NEG),
        ("1.00", None),  # equivocal: 0.80 to <1.20
    ],
)
def test_pre_kt_serostatus_reads_the_interpretation_not_a_boolean(value, expected):
    r = _recipient()
    _pre_kt_igg(r, value)
    assert r.pre_kt_igg_serostatus == expected


@pytest.mark.django_db
def test_an_equivocal_recipient_is_undetermined_exactly_as_a_missing_draw_is():
    """Not a third bucket. The same None an absent pre-KT draw produces, so every
    consumer that already refuses to guess on a missing serostatus needs no
    change to handle the grayzone."""
    equivocal = _recipient("SCMVR01")
    _pre_kt_igg(equivocal, "1.00")
    no_draw = _recipient("SCMVR02")
    RecipientVisit.objects.create(
        recipient=no_draw, timepoint_label="pre_kt", actual_visit_date=GEN2_DRAW
    )
    assert equivocal.pre_kt_igg_serostatus is None
    assert no_draw.pre_kt_igg_serostatus is None


@pytest.mark.django_db
def test_the_same_value_reads_differently_either_side_of_the_advisory():
    """1.50 AU/mL is non-reactive on first-generation reagent and reactive on
    second. The serostatus follows the row's own generation, and a frozen row is
    never re-read against the new ranges."""
    frozen = _recipient("SCMVR01")
    old_visit = RecipientVisit.objects.create(
        recipient=frozen, timepoint_label="pre_kt", actual_visit_date=date(2026, 6, 2)
    )
    CMVSerology.objects.create(
        recipient_visit=old_visit, value=Decimal("1.50"), drawn_date=date(2026, 6, 2)
    )
    current = _recipient("SCMVR02")
    _pre_kt_igg(current, "1.50")
    assert frozen.pre_kt_igg_serostatus == NEG
    assert current.pre_kt_igg_serostatus == POS


# --- The risk stratum needs no change --------------------------------------


@pytest.mark.django_db
def test_an_equivocal_recipient_leaves_the_risk_stratum_undetermined():
    """risk_stratum reads the two HAND-RECORDED serostatus columns, not the
    derived IgG reading, so this card does not touch it. The guarantee holds
    through its existing refusal to guess when either side is blank. Asserted
    here so that refusal cannot be removed without a failure pointing back at
    the grayzone that depends on it."""
    r = _recipient(donor_serostatus=POS, recipient_serostatus="")
    _pre_kt_igg(r, "1.00")  # equivocal
    assert r.pre_kt_igg_serostatus is None
    assert r.risk_stratum is None


# --- The donor baseline and the reconciliation flag ------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "value,expected",
    [("1.50", POS), ("0.50", NEG), ("1.00", None)],
)
def test_donor_baseline_serostatus_reads_the_interpretation(value, expected):
    d = _donor()
    CMVSerology.objects.create(donor=d, value=Decimal(value), drawn_date=GEN2_DRAW)
    assert d.baseline_serostatus == expected


@pytest.mark.django_db
def test_an_equivocal_donor_result_is_terminal():
    """The at-most-one-serology constraint means no repeat draw can resolve a
    donor's grayzone. There is no second row to create, so the donor simply has
    no established baseline serostatus and the flag must say so."""
    d = _donor()
    CMVSerology.objects.create(donor=d, value=Decimal("1.00"), drawn_date=GEN2_DRAW)

    # atomic() is not decoration. A constraint failure marks the surrounding
    # transaction broken, so every query after it raises TransactionManagementError
    # instead of doing what it says - which would make the assertions BELOW report
    # a fault they did not find. The block scopes the damage to the failed insert.
    with pytest.raises(IntegrityError), transaction.atomic():
        CMVSerology.objects.create(
            donor=d, value=Decimal("1.50"), drawn_date=date(2026, 7, 8)
        )

    # The point of the test: the constraint holds, so the grayzone result is the
    # donor's only one and the baseline stays undetermined for good.
    assert d.serologies.count() == 1
    assert d.baseline_serostatus is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "recorded,donor_value,expected",
    [
        (POS, "1.50", False),  # recorded POS, serology reactive -> compared, agree
        (NEG, "0.50", False),
        (POS, "0.50", True),   # compared, and they clash
        (NEG, "1.50", True),
        (POS, "1.00", None),   # equivocal donor result -> nothing to compare
        ("", "1.50", None),    # no recorded serostatus -> nothing to compare
    ],
)
def test_mismatch_flag_has_three_answers(recorded, donor_value, expected):
    d = _donor()
    CMVSerology.objects.create(donor=d, value=Decimal(donor_value), drawn_date=GEN2_DRAW)
    r = _recipient(donor=d, donor_serostatus=recorded)
    assert r.has_donor_serostatus_mismatch is expected


@pytest.mark.django_db
def test_not_comparable_is_distinct_from_compared_and_agreeing():
    """The whole point of the third answer. If these two collapsed, a reviewer
    reading the flag could not tell an all-clear from a non-comparison."""
    agreeing_donor = _donor("DCMVD01")
    CMVSerology.objects.create(
        donor=agreeing_donor, value=Decimal("1.50"), drawn_date=GEN2_DRAW
    )
    agreeing = _recipient("SCMVR01", donor=agreeing_donor, donor_serostatus=POS)

    silent_donor = _donor("DCMVD02")  # paired, but never drawn
    silent = _recipient("SCMVR02", donor=silent_donor, donor_serostatus=POS)

    assert agreeing.has_donor_serostatus_mismatch is False
    assert silent.has_donor_serostatus_mismatch is None


@pytest.mark.django_db
def test_the_flag_still_only_flags_and_never_overwrites():
    """Reconciliation stays a human judgment. Reading the flag leaves both
    stored facts exactly as they were entered, whichever of the three answers
    it produces."""
    d = _donor()
    CMVSerology.objects.create(donor=d, value=Decimal("0.50"), drawn_date=GEN2_DRAW)
    r = _recipient(donor=d, donor_serostatus=POS)

    assert r.has_donor_serostatus_mismatch is True
    r.refresh_from_db()
    d.refresh_from_db()
    assert r.donor_serostatus == POS
    assert d.baseline_serostatus == NEG
