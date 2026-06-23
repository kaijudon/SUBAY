from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from renova.registry.attribution import (
    CONCORDANCE_CALLS,
    LOCUS_CATALOG,
    SUPERINFECTION_STATUSES,
    counted_for_strain_identity,
    grade_concordance,
    is_hypervariable,
    is_resistance,
    locus_order,
)
from renova.registry.models import (
    Aliquot,
    CMVQuantitative,
    ConcordancePair,
    GenotypeCall,
    GenotypingResult,
    PipelineRun,
    Recipient,
    RecipientVisit,
)


# --- Step 1: pure locus catalog + concordance grader (no DB) ---


def test_locus_catalog_is_locked_three_groups():
    names = {s.name for s in LOCUS_CATALOG}
    assert {"gN", "gO", "UL144"} <= names  # hypervariable
    assert {"gB", "gH"} <= names  # conserved
    assert {"UL97", "UL54"} <= names  # resistance, labeled but not counted
    assert all(is_hypervariable(n) for n in ("gN", "gO", "UL144"))
    assert all(not is_hypervariable(n) for n in ("gB", "gH", "UL97", "UL54"))
    assert all(is_resistance(n) for n in ("UL97", "UL54"))
    assert all(not is_resistance(n) for n in ("gN", "gB"))


def test_resistance_not_counted_unknown_defaults_conserved():
    assert counted_for_strain_identity("gB") is True
    assert counted_for_strain_identity("gN") is True
    assert counted_for_strain_identity("UL97") is False
    # unknown locus -> conserved/counted/non-resistance
    assert counted_for_strain_identity("FOO") is True
    assert is_hypervariable("FOO") is False
    assert is_resistance("FOO") is False


def test_locus_order_hypervariable_first_resistance_last_unknown_between():
    assert locus_order("gN") < locus_order("gB")  # hypervariable before conserved
    assert locus_order("gB") < locus_order("FOO")  # conserved before unknown
    assert locus_order("FOO") < locus_order("UL97")  # unknown before resistance
    assert locus_order("gH") < locus_order("UL54")  # conserved before resistance


def _comp(locus, a, b, ra=True, rb=True):
    return {
        "locus": locus,
        "allele_a_set": set(a),
        "allele_b_set": set(b),
        "resolved_a": ra,
        "resolved_b": rb,
    }


def test_grade_choices_are_exactly_four_tiers():
    assert CONCORDANCE_CALLS == ("indeterminate", "discordant", "concordant", "high_confidence")
    assert SUPERINFECTION_STATUSES == ("none", "candidate", "confirmed")


@pytest.mark.parametrize(
    "comparisons,expected",
    [
        ([], "indeterminate"),  # 0 co-resolved
        ([_comp("gB", ["gB1"], ["gB1"])], "indeterminate"),  # 1 co-resolved
        # 2 co-resolved conserved loci agree -> concordant (no hypervariable)
        ([_comp("gB", ["gB1"], ["gB1"]), _comp("gH", ["gH1"], ["gH1"])], "concordant"),
        # 3 co-resolved agree but none hypervariable -> still concordant
        (
            [
                _comp("gB", ["gB1"], ["gB1"]),
                _comp("gH", ["gH1"], ["gH1"]),
                _comp("FOO", ["x"], ["x"]),
            ],
            "concordant",
        ),
        # 3 co-resolved agree incl one hypervariable -> high_confidence
        (
            [
                _comp("gB", ["gB1"], ["gB1"]),
                _comp("gH", ["gH1"], ["gH1"]),
                _comp("gN", ["gN2"], ["gN2"]),
            ],
            "high_confidence",
        ),
        # one co-resolved locus differs -> discordant
        (
            [_comp("gB", ["gB1"], ["gB3"]), _comp("gH", ["gH1"], ["gH1"])],
            "discordant",
        ),
    ],
)
def test_grade_concordance_thresholds(comparisons, expected):
    assert grade_concordance(comparisons) == expected


def test_resistance_locus_does_not_count_toward_strain_identity():
    # gB agrees + UL97 agrees, but UL97 is resistance -> only 1 counted -> indeterminate
    comparisons = [_comp("gB", ["gB1"], ["gB1"]), _comp("UL97", ["wt"], ["wt"])]
    assert grade_concordance(comparisons) == "indeterminate"


def test_unresolved_locus_excluded_from_co_resolved():
    # gB resolved in both, gH unresolved in one -> 1 co-resolved -> indeterminate
    comparisons = [
        _comp("gB", ["gB1"], ["gB1"]),
        _comp("gH", ["gH1"], ["gH1"], rb=False),
    ]
    assert grade_concordance(comparisons) == "indeterminate"


# --- Steps 2 & 3: ConcordancePair model + Recipient attribution properties ---


@pytest.fixture
def recipient(db):
    return Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )


def _result_for(recipient, calls, subject_id_offset=0):
    """A GenotypingResult anchored (through the tube) to `recipient`, carrying the
    given list of (locus, allele, sanger_call) calls."""
    editor = User.objects.create_user(username=f"bio{subject_id_offset}{len(calls)}{calls[0][1] if calls else 'x'}")
    v = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_7", actual_visit_date=date(2025, 1, 15)
    )
    a = Aliquot.objects.create(
        recipient_visit=v, matrix="plasma", collected_date=date(2025, 1, 15),
        initial_volume_ul=Decimal("1000"),
    )
    run = PipelineRun.objects.create(input_manifest_sha256=f"{subject_id_offset:064d}")
    res = GenotypingResult.objects.create(aliquot=a, pipeline_run=run, assay_type="sanger")
    for locus, allele, sc in calls:
        GenotypeCall.objects.create(
            result=res, locus=locus, allele=allele, sanger_call=sc, entered_by=editor
        )
    return res


def test_pair_suggested_call_and_co_resolved_count(recipient):
    a = _result_for(recipient, [("gB", "gB1", "R"), ("gH", "gH1", "R"), ("gN", "gN2", "R")], 1)
    b = _result_for(recipient, [("gB", "gB1", "R"), ("gH", "gH1", "R"), ("gN", "gN2", "R")], 2)
    pair = ConcordancePair.objects.create(
        recipient=recipient, recipient_result=a, comparator_result=b
    )
    assert pair.co_resolved_count == 3
    assert pair.suggested_concordance_call == "high_confidence"


def test_pair_without_comparator_is_indeterminate(recipient):
    a = _result_for(recipient, [("gB", "gB1", "R"), ("gH", "gH1", "R")], 1)
    pair = ConcordancePair.objects.create(recipient=recipient, recipient_result=a)
    assert pair.co_resolved_count == 0
    assert pair.suggested_concordance_call == "indeterminate"
    assert pair.comparator_subject is None


def test_pair_stored_call_is_not_overwritten_by_suggestion(recipient):
    a = _result_for(recipient, [("gB", "gB1", "R"), ("gH", "gH1", "R"), ("gN", "gN2", "R")], 1)
    b = _result_for(recipient, [("gB", "gB1", "R"), ("gH", "gH1", "R"), ("gN", "gN2", "R")], 2)
    # reviewer records false precision as indeterminate, differing from the suggestion
    pair = ConcordancePair.objects.create(
        recipient=recipient, recipient_result=a, comparator_result=b,
        concordance_call="indeterminate",
    )
    assert pair.suggested_concordance_call == "high_confidence"
    assert pair.concordance_call == "indeterminate"  # human override survives


def test_pair_clean_rejects_mismatched_subject(db, recipient):
    other = Recipient.objects.create(
        subject_id="SCMVR08", date_of_birth=date(1981, 1, 1), sex="F", kt_date=date(2025, 1, 1)
    )
    a = _result_for(recipient, [("gB", "gB1", "R")], 1)
    pair = ConcordancePair(recipient=other, recipient_result=a)
    with pytest.raises(ValidationError):
        pair.full_clean()


def test_pair_clean_rejects_self_comparison(recipient):
    a = _result_for(recipient, [("gB", "gB1", "R")], 1)
    pair = ConcordancePair(recipient=recipient, recipient_result=a, comparator_result=a)
    with pytest.raises(ValidationError):
        pair.full_clean()


def test_superinfection_requires_comparator(recipient):
    a = _result_for(recipient, [("gB", "gB1", "R")], 1)
    pair = ConcordancePair(
        recipient=recipient, recipient_result=a, superinfection_status="confirmed"
    )
    with pytest.raises(ValidationError):
        pair.full_clean()


def _seed_qnat(recipient, value):
    v = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="day_90", actual_visit_date=date(2025, 4, 1)
    )
    CMVQuantitative.objects.create(
        recipient_visit=v, value=Decimal(value), drawn_date=date(2025, 4, 1)
    )


def _seed_pre_kt_serostatus(recipient, value):
    v = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="pre_kt", actual_visit_date=date(2025, 1, 1)
    )
    from renova.registry.models import CMVSerology

    CMVSerology.objects.create(
        recipient_visit=v, value=Decimal(value), drawn_date=date(2025, 1, 1)
    )


def test_source_label_none_without_qnat(recipient):
    assert recipient.has_positive_qnat is False
    assert recipient.source_label is None


def test_source_label_primary_is_r_neg_qnat_pos_no_seroconversion(recipient):
    _seed_pre_kt_serostatus(recipient, "1.0")  # IgG 1.0 < 2.0 -> NEG (R-)
    _seed_qnat(recipient, "1500")  # QNAT+
    assert recipient.has_positive_qnat is True
    assert recipient.pre_kt_igg_serostatus == "NEG"
    assert recipient.source_label == "primary"


def test_source_label_reactivation_is_r_pos_qnat_pos(recipient):
    _seed_pre_kt_serostatus(recipient, "3.0")  # IgG 3.0 >= 2.0 -> POS (R+)
    _seed_qnat(recipient, "1500")
    assert recipient.source_label == "reactivation"


def test_source_label_none_when_serostatus_unknown(recipient):
    _seed_qnat(recipient, "1500")  # QNAT+ but no pre_kt serology -> serostatus unknown
    assert recipient.pre_kt_igg_serostatus is None
    assert recipient.source_label is None


def test_source_label_priority_confirmed_beats_primary(recipient):
    _seed_pre_kt_serostatus(recipient, "1.0")  # R-
    _seed_qnat(recipient, "1500")  # QNAT+  -> would be primary
    a = _result_for(recipient, [("gB", "gB1", "R")], 1)
    b = _result_for(recipient, [("gB", "gB3", "R")], 2)
    pair = ConcordancePair.objects.create(
        recipient=recipient, recipient_result=a, comparator_result=b,
        superinfection_status="candidate",
    )
    # candidate does NOT upgrade
    assert recipient.source_label == "primary"
    # confirmed flips it to donor_derived (priority wins)
    pair.superinfection_status = "confirmed"
    pair.save()
    assert recipient.source_label == "donor_derived"


def test_has_positive_qnat_below_lod_is_not_positive(recipient):
    _seed_qnat(recipient, "10")  # below 34.5 LoD
    assert recipient.has_positive_qnat is False
