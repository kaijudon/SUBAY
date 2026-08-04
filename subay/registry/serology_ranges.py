"""CMV serology reference ranges, versioned by assay reagent generation (Slice 17).

The SPMC Transplant Immunology Unit moved to second-generation assay reagents and
issued new reference values with immediate effect on 3 June 2026. A value read on
first-generation reagent and the same number read on second-generation reagent are
different measurements, so results are NEVER re-interpreted across the boundary
(DEC-030 decision 2). The register holds both interpretations at once and every
consumer is told which one applies.

Isolated here as pure functions and named constants, the way `scheduling.py`,
`episodes.py` and `safety.py` isolate their rules, so the bands are testable
without a database and the next advisory is a discoverable edit rather than a
hunt for magic numbers.

Units: AU/mL on both channels, both generations. The advisory's CMV IgG row reads
"IU/mL" - that is a transcription error, confirmed with the lab on 2026-08-04
(DEC-032). No stored value is ever rescaled.
"""
from datetime import date
from decimal import Decimal

# Reagent generations. Stored per row rather than derived from the draw date:
# deriving would mean that correcting a mistyped draw date silently re-interprets
# a frozen clinical reading, which is the exact failure DEC-030 decision 2 exists
# to prevent. It also covers what a date cannot - a sample run on first-generation
# reagent whose result only reaches the register later.
GEN1 = "gen1"
GEN2 = "gen2"

REAGENT_GENERATION_CHOICES = [
    (GEN1, "1st generation (before 2026-06-03)"),
    (GEN2, "2nd generation (from 2026-06-03)"),
]

# The advisory took effect ON this day, so the boundary is inclusive. Declared
# once here; the interpretation rule and the backfill both read it.
ADVISORY_EFFECTIVE = date(2026, 6, 3)


def generation_for(drawn_date):
    """The reagent generation in force on `drawn_date`.

    The default for a newly entered row and the rule the 0020 backfill applies.
    A data manager may override the stored value for a late-entered sample that
    was run on first-generation reagent.
    """
    return GEN2 if drawn_date >= ADVISORY_EFFECTIVE else GEN1


# --- Interpretations -------------------------------------------------------
#
# Three states plus None. None means "not measured" and is NOT a fourth clinical
# answer; it mirrors the existing result_status = "missing" case, where a QC or
# lab failure means no observation was obtained at all.
NON_REACTIVE = "non_reactive"
EQUIVOCAL = "equivocal"
REACTIVE = "reactive"

SEROLOGY_INTERPRETATION_CHOICES = [
    (NON_REACTIVE, "Non-reactive"),
    (EQUIVOCAL, "Equivocal"),
    (REACTIVE, "Reactive"),
]


# --- Bands, per channel per generation. All AU/mL (DEC-032) ----------------
#
# Each band is [lower, upper): inclusive at the lower edge, exclusive at the
# upper. A value at `equivocal_from` is equivocal; a value at `reactive_from` is
# reactive.

# First generation: ONE cutoff shared by both channels, no grayzone (DEC-016).
# Expressed as a band whose two edges coincide, so the same comparison covers
# both generations and there is no separate legacy code path to keep in step.
# Kept as a live constant, not deleted: frozen rows are still read against it.
GEN1_REACTIVE_FROM_AU_ML = Decimal("2.00")

# Second generation, per the advisory of 3 June 2026.
GEN2_IGG_EQUIVOCAL_FROM_AU_ML = Decimal("0.80")
GEN2_IGG_REACTIVE_FROM_AU_ML = Decimal("1.20")
GEN2_IGM_EQUIVOCAL_FROM_AU_ML = Decimal("2.00")
GEN2_IGM_REACTIVE_FROM_AU_ML = Decimal("4.20")

# (equivocal_from, reactive_from) keyed by generation, one map per channel. The
# two channels diverged at the second generation - 2.00 AU/mL is reactive on IgG
# and equivocal on IgM - which is why a single shared threshold can no longer
# express the rule and is being split rather than retuned.
_IGG_BANDS = {
    GEN1: (GEN1_REACTIVE_FROM_AU_ML, GEN1_REACTIVE_FROM_AU_ML),
    GEN2: (GEN2_IGG_EQUIVOCAL_FROM_AU_ML, GEN2_IGG_REACTIVE_FROM_AU_ML),
}
_IGM_BANDS = {
    GEN1: (GEN1_REACTIVE_FROM_AU_ML, GEN1_REACTIVE_FROM_AU_ML),
    GEN2: (GEN2_IGM_EQUIVOCAL_FROM_AU_ML, GEN2_IGM_REACTIVE_FROM_AU_ML),
}


def _interpret(value, bands, generation):
    if value is None:
        return None
    equivocal_from, reactive_from = bands[generation]
    if value >= reactive_from:
        return REACTIVE
    if value >= equivocal_from:
        return EQUIVOCAL
    return NON_REACTIVE


def interpret_igg(value, generation):
    """Three-state IgG reading under the ranges in force for `generation`."""
    return _interpret(value, _IGG_BANDS, generation)


def interpret_igm(value, generation):
    """Three-state IgM reading under the ranges in force for `generation`."""
    return _interpret(value, _IGM_BANDS, generation)


def bands_for(generation):
    """The (equivocal_from, reactive_from) pair per channel for `generation`.

    The public protocol page publishes the ranges rather than merely applying
    them, and it must publish the ones the interpreter actually uses. Reading
    the same map `interpret_igg`/`interpret_igm` read is the only way the page
    and the software cannot drift; retyping the numbers into a view would
    reintroduce exactly the staleness slice 17 exists to remove.
    """
    return {"igg": _IGG_BANDS[generation], "igm": _IGM_BANDS[generation]}


# --- Serostatus ------------------------------------------------------------

POS = "POS"
NEG = "NEG"


def serostatus_from(interpretation):
    """POS / NEG / None from a three-state IgG reading (slice 17, ticket 02).

    Both the recipient's pre-KT serostatus and the donor's baseline serostatus
    make this same translation, and they must never disagree about it, so it is
    written once here rather than twice at the two call sites.

    An EQUIVOCAL reading yields None, exactly as an absent draw does. The PI's
    ruling is that the grayzone is not a category: a subject whose IgG lands in
    it has no established serostatus until a repeat draw resolves it. Rounding
    equivocal towards either answer would invent a stratification the lab did
    not support.
    """
    if interpretation == REACTIVE:
        return POS
    if interpretation == NON_REACTIVE:
        return NEG
    return None  # equivocal, or not measured at all
