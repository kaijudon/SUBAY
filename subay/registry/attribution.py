"""Pure source-attribution & genotype-concordance grader (Slice 11) — ORM-free
so it unit-tests with no DB, mirroring episodes.py / scheduling.py.

A reviewer never invents a concordance tier from a hunch: the graded asymmetric
thresholds derive from the per-locus allele comparison so a suggested call
reproduces exactly from the stored GenotypeCalls. The reviewer's own
`concordance_call` is recorded SEPARATELY and is never auto-overwritten (false
precision is recordable as `indeterminate`).

LOCUS_CATALOG is LOCKED and structured (never free text), like ASSAY_TYPE_CHOICES.
Three groups, exported hypervariable-first → conserved → resistance-last:

- hypervariable (strain-identity, high-information): gN, gO, UL144
- conserved      (strain-identity):                  gB, gH
- resistance     (NOT counted for strain identity):  UL97, UL54

An unknown locus defaults to conserved / counted / non-resistance, ordered after
the catalogued conserved loci (deterministically by name in the row sort) but
always before the resistance block, so "resistance-last" holds.
"""
from __future__ import annotations

from typing import NamedTuple

# The four concordance tiers, canonical here so models.CONCORDANCE_CALL_CHOICES
# can never drift from what the grader returns (the SEVERITY_TIERS precedent).
CONCORDANCE_CALLS = ("indeterminate", "discordant", "concordant", "high_confidence")
# Mixed-infection donor-derived superinfection flag — candidate vs confirmed.
SUPERINFECTION_STATUSES = ("none", "candidate", "confirmed")

STRAIN_IDENTITY_NOTE = "not counted for strain identity"


class LocusSpec(NamedTuple):
    name: str
    hypervariable: bool
    resistance: bool
    order: int  # ascending: hypervariable < conserved < resistance


# Order values leave a gap (group bases 0 / 100 / 300) so an unknown conserved
# locus can sort after the catalogued conserved block (200) yet before resistance.
LOCUS_CATALOG = [
    LocusSpec("gN", True, False, 0),
    LocusSpec("gO", True, False, 1),
    LocusSpec("UL144", True, False, 2),
    LocusSpec("gB", False, False, 100),
    LocusSpec("gH", False, False, 101),
    LocusSpec("UL97", False, True, 300),
    LocusSpec("UL54", False, True, 301),
]
_SPEC_BY_NAME = {spec.name: spec for spec in LOCUS_CATALOG}
_UNKNOWN_ORDER = 200  # conserved-group slot, after catalogued conserved, before resistance


def locus_order(name: str) -> int:
    """Ascending sort key: hypervariable first, resistance last. Unknown loci land
    in the conserved band (after the catalogued conserved loci)."""
    spec = _SPEC_BY_NAME.get(name)
    return spec.order if spec is not None else _UNKNOWN_ORDER


def is_hypervariable(name: str) -> bool:
    spec = _SPEC_BY_NAME.get(name)
    return spec.hypervariable if spec is not None else False


def is_resistance(name: str) -> bool:
    spec = _SPEC_BY_NAME.get(name)
    return spec.resistance if spec is not None else False


def counted_for_strain_identity(name: str) -> bool:
    """Resistance loci are catalogued but excluded from strain identity. Everything
    else (incl. unknown loci) counts."""
    return not is_resistance(name)


def co_resolved_loci(comparisons):
    """Strain-identity loci resolved in BOTH members (resistance excluded). The
    single definition both the grader and the per-pair count read, so they cannot
    disagree."""
    return [
        c
        for c in comparisons
        if c.get("resolved_a")
        and c.get("resolved_b")
        and counted_for_strain_identity(c["locus"])
    ]


def _differs(comparison) -> bool:
    return set(comparison["allele_a_set"]) != set(comparison["allele_b_set"])


def grade_concordance(comparisons) -> str:
    """Graded asymmetric thresholds (AC3) over per-locus comparisons. Each item:
    {locus, allele_a_set, allele_b_set, resolved_a, resolved_b}.

    - `< 2` co-resolved strain-identity loci      -> indeterminate
    - `>= 1` co-resolved locus differs            -> discordant
    - all agree, co-resolved `>= 3` incl `>= 1` hypervariable -> high_confidence
    - all agree, co-resolved `>= 2`               -> concordant
    """
    coresolved = co_resolved_loci(comparisons)
    if len(coresolved) < 2:
        return "indeterminate"
    if any(_differs(c) for c in coresolved):
        return "discordant"
    if len(coresolved) >= 3 and any(is_hypervariable(c["locus"]) for c in coresolved):
        return "high_confidence"
    return "concordant"
