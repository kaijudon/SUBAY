"""Slice 02 — baseline fields + derived values (AC1–AC6).

Every computable value stays derived (@property), never a stored column, so a
stored fact and its computed value can never silently disagree.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.db.utils import IntegrityError as DBIntegrityError

from subay.registry.models import (
    CMVSerology,
    Donor,
    OtherCondition,
    Recipient,
)


def _recipient(**kw):
    base = dict(
        subject_id="SCMVR07",
        date_of_birth=date(1980, 1, 1),
        sex="M",
        kt_date=date(2025, 1, 1),
    )
    base.update(kw)
    return Recipient.objects.create(**base)


def _donor(**kw):
    base = dict(
        subject_id="DCMVD01",
        date_of_birth=date(1975, 1, 1),
        sex="F",
    )
    base.update(kw)
    return Donor.objects.create(**base)


# AC1 — risk_stratum derived, no stored column.
@pytest.mark.django_db
def test_risk_stratum_is_not_a_stored_field():
    field_names = [f.name for f in Recipient._meta.get_fields()]
    assert "risk_stratum" not in field_names


@pytest.mark.django_db
def test_risk_stratum_recomputes_without_save():
    r = _recipient(donor_serostatus="POS", recipient_serostatus="NEG")
    assert r.risk_stratum == "high"
    r.recipient_serostatus = "POS"  # mutate in memory, no save
    assert r.risk_stratum == "intermediate"


# AC2 — three-state confounders: "no" (False) distinguishable from "not asked" (None).
@pytest.mark.django_db
def test_confounders_are_three_state_nullable_booleans():
    no_dm = _recipient(subject_id="SCMVR07", has_diabetes=False)
    unknown_dm = _recipient(subject_id="SCMVR08", has_diabetes=None)
    yes_dm = _recipient(subject_id="SCMVR09", has_diabetes=True)
    assert no_dm.has_diabetes is False
    assert unknown_dm.has_diabetes is None
    assert yes_dm.has_diabetes is True
    # has_hypertension is also three-state
    assert _recipient(subject_id="SCMVR10", has_hypertension=False).has_hypertension is False


# AC3 — dialysis_vintage_months + induction_agent queryable; absence is explicit.
@pytest.mark.django_db
def test_induction_agent_absence_is_queryable():
    _recipient(subject_id="SCMVR07", induction_agent="none")
    _recipient(subject_id="SCMVR08", induction_agent="atg")
    _recipient(subject_id="SCMVR09", induction_agent=None)  # not recorded
    none_only = Recipient.objects.filter(induction_agent="none")
    assert [r.subject_id for r in none_only] == ["SCMVR07"]


@pytest.mark.django_db
def test_dialysis_vintage_months_is_queryable_integer():
    _recipient(subject_id="SCMVR07", dialysis_vintage_months=24)
    assert Recipient.objects.filter(dialysis_vintage_months__gte=12).count() == 1


# AC4 — OtherCondition: one row per condition, no column-per-possibility.
@pytest.mark.django_db
def test_other_condition_is_long_not_wide():
    r = _recipient()
    OtherCondition.objects.create(recipient=r, condition="gout")
    OtherCondition.objects.create(recipient=r, condition="prior cmv")
    assert r.other_conditions.count() == 2
    # No wide boolean-per-condition columns leaked onto Recipient.
    field_names = [f.name for f in Recipient._meta.get_fields()]
    assert "gout" not in field_names
    assert "prior_cmv" not in field_names


# AC5 — Donor thin: <=1 serology, single draw date, no visit timeline.
@pytest.mark.django_db
def test_donor_carries_type_and_optional_relation():
    d = _donor(donor_type="living", relation="sibling")
    assert d.donor_type == "living"
    assert d.relation == "sibling"


@pytest.mark.django_db
def test_donor_has_no_visit_timeline():
    # Slice 03 adds a minimal DonorVisit (donor + draw_date) reachable via
    # `visits`, but a donor still gets NO recipient-grade timeline: the related
    # model carries no nominal_day/timepoint/closure scheduling.
    rel = Donor._meta.get_field("visits").related_model
    assert rel.__name__ == "DonorVisit"
    for forbidden in ("nominal_day", "timepoint_label", "closure_shifted",
                      "closure_reason", "shift_days_from_nominal", "actual_visit_date"):
        assert not hasattr(rel, forbidden)


@pytest.mark.django_db
def test_donor_allows_at_most_one_serology():
    d = _donor()
    CMVSerology.objects.create(donor=d, value=Decimal("1.0"), drawn_date=date(2024, 12, 1))
    with pytest.raises((IntegrityError, DBIntegrityError)):
        CMVSerology.objects.create(donor=d, value=Decimal("3.0"), drawn_date=date(2024, 12, 2))


@pytest.mark.django_db
def test_donor_baseline_serostatus_from_single_serology():
    d = _donor()
    assert d.baseline_serostatus is None  # no draw yet
    CMVSerology.objects.create(donor=d, value=Decimal("3.0"), drawn_date=date(2024, 12, 1))
    d.refresh_from_db()
    assert d.baseline_serostatus == "POS"


# AC6 — mismatch surfaced as a flag, never overwritten, never raised.
@pytest.mark.django_db
def test_mismatch_flag_true_when_recorded_disagrees_with_donor_serology():
    d = _donor()
    CMVSerology.objects.create(donor=d, value=Decimal("1.0"), drawn_date=date(2024, 12, 1))  # NEG
    r = _recipient(donor=d, donor_serostatus="POS")
    assert r.has_donor_serostatus_mismatch is True
    # Neither stored value is silently overwritten by reading the flag.
    r.refresh_from_db()
    assert r.donor_serostatus == "POS"
    assert d.baseline_serostatus == "NEG"


@pytest.mark.django_db
def test_mismatch_flag_false_when_agree():
    d = _donor()
    CMVSerology.objects.create(donor=d, value=Decimal("3.0"), drawn_date=date(2024, 12, 1))  # POS
    r = _recipient(donor=d, donor_serostatus="POS")
    assert r.has_donor_serostatus_mismatch is False


@pytest.mark.django_db
def test_mismatch_flag_not_comparable_when_either_side_missing():
    """This asserted False on both counts until slice 17 ticket 02.

    False is a claim: the two sides were compared and they agreed. Neither case
    below was ever compared at all, so answering False told a reviewer that the
    weakest possible evidence was a clean all-clear. The property now has a third
    answer for it. AC6's real guarantee, that a genuine clash is surfaced and
    never overwritten, is untouched and still asserted above.
    """
    r_no_donor = _recipient(subject_id="SCMVR07", donor_serostatus="POS")
    assert r_no_donor.has_donor_serostatus_mismatch is None
    d = _donor()  # paired, but no serology to compare against
    r = _recipient(subject_id="SCMVR08", donor=d, donor_serostatus="POS")
    assert r.has_donor_serostatus_mismatch is None
    # Distinct from the agreeing case, which still answers False.
    d2 = _donor(subject_id="SCMVD09")
    CMVSerology.objects.create(donor=d2, value=Decimal("3.0"), drawn_date=date(2024, 12, 1))
    r2 = _recipient(subject_id="SCMVR09", donor=d2, donor_serostatus="POS")
    assert r2.has_donor_serostatus_mismatch is False


@pytest.mark.django_db
def test_mismatch_flag_not_comparable_when_donor_serology_is_equivocal():
    """An equivocal donor result yields no baseline serostatus, so there is
    nothing to compare the recorded value against.

    A donor has at most one baseline serology, so this is terminal: no repeat
    draw can resolve it. Before the third answer existed this presented as a
    clean agreement, which is the specific failure the equivocal band makes
    common rather than rare.
    """
    d = _donor(subject_id="SCMVD10")
    CMVSerology.objects.create(
        donor=d, value=Decimal("1.00"), drawn_date=date(2026, 7, 1)  # gen2 IgG equivocal
    )
    r = _recipient(subject_id="SCMVR10", donor=d, donor_serostatus="POS")
    assert d.baseline_serostatus is None
    assert r.has_donor_serostatus_mismatch is None
