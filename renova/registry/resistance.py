"""Pure UL97/UL54 antiviral-resistance rollup (Slice 12) — ORM-free so it
unit-tests with no DB, mirroring attribution.py / episodes.py.

Resistance surveillance is kept DISTINCT from strain-identity genotyping so drug
attribution is never pooled away. The two reported loci have SEPARATE per-locus
R-bucket denominators that are NEVER summed across loci — ganciclovir-only (UL97)
and cross-resistance (UL54) attribution stay separable. `rollup_by_locus` always
returns both loci as their own keys; there is deliberately no path that adds a
UL97 count to a UL54 count (the load-bearing AC2 guarantee).

The duty-to-disclose SOP fires on EXACTLY one intersection: an established
resistance variant in a patient with active virological failure. "Active
virological failure" is derived from the QNAT at the call against the assay LoQ
(34.5 IU/mL) — the SAME positivity bar episodes.py / attribution use (DEC-023),
so the three modules can never disagree about what "positive" means.
"""
from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple

# The two reported resistance loci, LOCKED here so models.RESISTANCE_LOCUS_CHOICES
# can never drift (the SEVERITY_TIERS / CONCORDANCE_CALLS precedent).
RESISTANCE_LOCI = ("UL97", "UL54")
# Per-variant interpretive tier, curated three-tier surveillance.
RESISTANCE_TIERS = ("established", "polymorphism", "unknown")
# Positivity bar for "active virological failure"; cross-checked == CMVQuantitative.LOQ
# in the tests so the resistance flag and the episode deriver share one threshold.
ACTIVE_FAILURE_THRESHOLD = Decimal("34.5")


class ResistanceCallView(NamedTuple):
    """One resistance call in the shape the rollup consumes — ORM-free."""

    locus: str
    status: str  # R / F / N (the Sanger taxonomy)
    established_present: bool


class LocusRollup(NamedTuple):
    r_bucket: int  # count of status == "R" calls at this locus (its own denominator)
    n_total: int
    established_present: bool


def is_active_virological_failure(
    qnat: Decimal | None, threshold: Decimal = ACTIVE_FAILURE_THRESHOLD
) -> bool:
    """Viremic at the call: a QNAT at/above the assay LoQ. None (no QNAT recorded)
    is not failure."""
    return qnat is not None and qnat >= threshold


def return_of_results(
    established_present: bool,
    qnat: Decimal | None,
    threshold: Decimal = ACTIVE_FAILURE_THRESHOLD,
) -> bool:
    """The tiered duty-to-disclose flag — fires on EXACTLY the established-resistance
    ∩ active-virological-failure intersection."""
    return bool(established_present) and is_active_virological_failure(qnat, threshold)


def rollup_by_locus(calls) -> dict[str, LocusRollup]:
    """Per-locus surveillance rollup. ALWAYS returns both RESISTANCE_LOCI as
    separate keys (each with its own r_bucket denominator) and NEVER sums across
    loci. `calls` are ResistanceCallViews or plain (locus, status,
    established_present) tuples; a call on an out-of-vocabulary locus is ignored,
    never pooled into a resistance bucket."""
    r_bucket = {locus: 0 for locus in RESISTANCE_LOCI}
    n_total = {locus: 0 for locus in RESISTANCE_LOCI}
    established = {locus: False for locus in RESISTANCE_LOCI}
    for raw in calls:
        call = raw if isinstance(raw, ResistanceCallView) else ResistanceCallView(*raw)
        if call.locus not in r_bucket:
            continue  # never pool an unknown locus into UL97/UL54
        n_total[call.locus] += 1
        if call.status == "R":
            r_bucket[call.locus] += 1
        if call.established_present:
            established[call.locus] = True
    return {
        locus: LocusRollup(r_bucket[locus], n_total[locus], established[locus])
        for locus in RESISTANCE_LOCI
    }
