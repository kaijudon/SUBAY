"""Slice 12 — Resistance surveillance (UL97 / UL54).

`ResistanceCall` records a resistance locus (UL97/UL54 only), an R/F/N status, the
QNAT at the call, and a long/1NF list of `ResistanceVariant` rows each carrying a
three-tier interpretation. The established-present bool, the active-virological-
failure flag, and the tiered return-of-results flag are all DERIVED @property
(derive-don't-store) so they can never drift from the variant data. UL97 and UL54
keep SEPARATE per-locus R-bucket denominators and are never pooled. Subject /
visit / sample-date are derived through the tube (the slice-10 precedent).
"""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction

from renova.registry.resistance import (
    ACTIVE_FAILURE_THRESHOLD,
    RESISTANCE_LOCI,
    RESISTANCE_TIERS,
    is_active_virological_failure,
    return_of_results,
    rollup_by_locus,
)
from renova.registry.models import (
    RESISTANCE_LOCUS_CHOICES,
    RESISTANCE_TIER_CHOICES,
    Aliquot,
    CMVQuantitative,
    PipelineRun,
    Recipient,
    RecipientVisit,
    ResistanceCall,
    ResistanceVariant,
    GenotypingResult,
)


# --- Step 1: pure rollup module (no DB) ---


def test_resistance_loci_are_locked_two_separate():
    assert RESISTANCE_LOCI == ("UL97", "UL54")
    assert RESISTANCE_TIERS == ("established", "polymorphism", "unknown")


def test_active_failure_threshold_matches_assay_loq():
    # The same positivity bar episodes/attribution use (DEC-023), so the three
    # modules can never disagree about "positive".
    assert ACTIVE_FAILURE_THRESHOLD == CMVQuantitative.LOQ


@pytest.mark.parametrize(
    "qnat,expected",
    [
        (Decimal("34.5"), True),  # at LoQ -> viremic
        (Decimal("1500"), True),
        (Decimal("10"), False),  # below LoQ
        (None, False),  # no QNAT recorded
    ],
)
def test_is_active_virological_failure(qnat, expected):
    assert is_active_virological_failure(qnat) is expected


@pytest.mark.parametrize(
    "established,qnat,expected",
    [
        (True, Decimal("1500"), True),  # the actionable intersection
        (True, Decimal("10"), False),  # established but no active failure
        (True, None, False),
        (False, Decimal("1500"), False),  # active failure but no established variant
        (False, None, False),
    ],
)
def test_return_of_results_intersection(established, qnat, expected):
    assert return_of_results(established, qnat) is expected


def test_rollup_always_returns_both_loci_separately():
    rollup = rollup_by_locus([])
    assert set(rollup) == {"UL97", "UL54"}
    for locus in RESISTANCE_LOCI:
        assert rollup[locus].r_bucket == 0
        assert rollup[locus].n_total == 0
        assert rollup[locus].established_present is False


def test_rollup_per_locus_buckets_never_pooled():
    calls = [
        ("UL97", "R", True),
        ("UL97", "R", False),
        ("UL97", "F", False),  # not resolved -> not in r_bucket
        ("UL54", "R", False),
    ]
    rollup = rollup_by_locus(calls)
    # UL97 has its own denominator, unaffected by UL54 rows and vice-versa.
    assert rollup["UL97"].r_bucket == 2
    assert rollup["UL97"].n_total == 3
    assert rollup["UL97"].established_present is True
    assert rollup["UL54"].r_bucket == 1
    assert rollup["UL54"].n_total == 1
    assert rollup["UL54"].established_present is False
    # the two are never summed
    assert rollup["UL97"].r_bucket + rollup["UL54"].r_bucket == 3


def test_rollup_ignores_unknown_locus_never_pools():
    rollup = rollup_by_locus([("gB", "R", True), ("UL97", "R", False)])
    assert rollup["UL97"].n_total == 1
    assert rollup["UL97"].established_present is False
    assert rollup["UL54"].n_total == 0


# --- Steps 2 & 3: ResistanceCall + ResistanceVariant models ---


@pytest.fixture
def recipient(db):
    return Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )


def _result_for(recipient, tag="1"):
    """A GenotypingResult anchored (through the tube) to `recipient`."""
    v = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_90", actual_visit_date=date(2025, 4, 1)
    )
    a = Aliquot.objects.create(
        recipient_visit=v, matrix="plasma", collected_date=date(2025, 4, 1),
        initial_volume_ul=Decimal("1000"),
    )
    run = PipelineRun.objects.create(input_manifest_sha256=(tag * 64)[:64])
    return GenotypingResult.objects.create(aliquot=a, pipeline_run=run, assay_type="sanger")


def test_locus_and_tier_choices_come_from_pure_module():
    assert {c for c, _ in RESISTANCE_LOCUS_CHOICES} == {"UL97", "UL54"}
    assert {c for c, _ in RESISTANCE_TIER_CHOICES} == set(RESISTANCE_TIERS)


def test_illegal_locus_rejected_by_clean(recipient):
    res = _result_for(recipient)
    call = ResistanceCall(result=res, locus="gB", status="R")
    with pytest.raises(ValidationError):
        call.full_clean()


def test_illegal_status_rejected_by_clean(recipient):
    res = _result_for(recipient)
    call = ResistanceCall(result=res, locus="UL97", status="X")
    with pytest.raises(ValidationError):
        call.full_clean()


def test_db_constraint_rejects_bad_locus_on_bare_save(recipient):
    res = _result_for(recipient)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ResistanceCall.objects.create(result=res, locus="UL56", status="R")


def test_variant_list_is_long_one_row_per_variant(recipient):
    res = _result_for(recipient)
    call = ResistanceCall.objects.create(result=res, locus="UL97", status="R")
    ResistanceVariant.objects.create(resistance_call=call, variant="C592G", tier="established")
    ResistanceVariant.objects.create(resistance_call=call, variant="M460V", tier="polymorphism")
    assert call.variants.count() == 2


def test_established_present_is_derived_property_not_stored():
    field_names = {f.name for f in ResistanceCall._meta.get_fields()}
    assert "established_resistance_present" not in field_names
    assert "subject" not in field_names
    assert "visit" not in field_names
    assert "drawn_date" not in field_names
    assert isinstance(ResistanceCall.established_resistance_present, property)
    assert isinstance(ResistanceCall.subject, property)
    assert isinstance(ResistanceCall.visit, property)


def test_established_present_reflects_variant_tiers(recipient):
    res = _result_for(recipient)
    call = ResistanceCall.objects.create(result=res, locus="UL97", status="R")
    assert call.established_resistance_present is False
    ResistanceVariant.objects.create(resistance_call=call, variant="P1", tier="polymorphism")
    ResistanceVariant.objects.create(resistance_call=call, variant="U1", tier="unknown")
    assert call.established_resistance_present is False
    ResistanceVariant.objects.create(resistance_call=call, variant="C592G", tier="established")
    assert call.established_resistance_present is True


def test_subject_and_sample_date_derived_through_tube(recipient):
    res = _result_for(recipient)
    call = ResistanceCall.objects.create(result=res, locus="UL97", status="R")
    assert call.subject.subject_id == "SCMVR07"
    assert call.sample_date == date(2025, 4, 1)
    assert call.visit.timepoint_label == "day_90"


def test_result_fk_is_protect(recipient):
    res = _result_for(recipient)
    ResistanceCall.objects.create(result=res, locus="UL97", status="R")
    f = ResistanceCall._meta.get_field("result")
    assert f.remote_field.on_delete is models.PROTECT
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            res.delete()


def test_variant_fk_is_cascade(recipient):
    res = _result_for(recipient)
    call = ResistanceCall.objects.create(result=res, locus="UL97", status="R")
    ResistanceVariant.objects.create(resistance_call=call, variant="C592G", tier="established")
    f = ResistanceVariant._meta.get_field("resistance_call")
    assert f.remote_field.on_delete is models.CASCADE
    call.delete()
    assert ResistanceVariant.objects.count() == 0


# --- AC3: the actionable return-of-results matrix ---


def _call_with(recipient, tier, qnat, tag="1"):
    res = _result_for(recipient, tag)
    call = ResistanceCall.objects.create(
        result=res, locus="UL97", status="R",
        qnat_iu_ml=Decimal(qnat) if qnat is not None else None,
    )
    if tier is not None:
        ResistanceVariant.objects.create(resistance_call=call, variant="V", tier=tier)
    return call


@pytest.mark.parametrize(
    "tier,qnat,flag",
    [
        ("established", "1500", True),  # established + active failure -> flag
        ("established", "10", False),  # established + sub-LoQ -> no flag
        ("established", None, False),  # established + no QNAT -> no flag
        ("polymorphism", "1500", False),  # not established
        ("unknown", "1500", False),
        (None, "1500", False),  # no variants
    ],
)
def test_return_of_results_flag_matrix(recipient, tier, qnat, flag):
    call = _call_with(recipient, tier, qnat)
    assert call.return_of_results_flag is flag


def test_has_active_virological_failure_uses_loq(recipient):
    res = _result_for(recipient)
    call = ResistanceCall.objects.create(
        result=res, locus="UL97", status="R", qnat_iu_ml=Decimal("34.5")
    )
    assert call.has_active_virological_failure is True


# --- AC2 check 2c: subject rollup, both loci, never pooled ---


def test_recipient_resistance_rollup_keeps_loci_separate(recipient):
    r97 = _result_for(recipient, "1")
    r54 = _result_for(recipient, "2")
    ResistanceCall.objects.create(result=r97, locus="UL97", status="R")
    ResistanceCall.objects.create(result=r97, locus="UL97", status="F")
    ResistanceCall.objects.create(result=r54, locus="UL54", status="R")
    rollup = recipient.resistance_rollup
    assert set(rollup) == {"UL97", "UL54"}
    assert rollup["UL97"].r_bucket == 1
    assert rollup["UL97"].n_total == 2
    assert rollup["UL54"].r_bucket == 1
    assert rollup["UL54"].n_total == 1


# --- History (consistency with every prior outcome model) ---


def test_history_tracked(recipient):
    res = _result_for(recipient)
    call = ResistanceCall.objects.create(result=res, locus="UL97", status="R")
    assert call.history.count() == 1
    variant = ResistanceVariant.objects.create(
        resistance_call=call, variant="C592G", tier="established"
    )
    assert variant.history.count() == 1
