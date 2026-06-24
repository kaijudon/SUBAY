"""Pure safety release-timeliness predicates (Slice 14) — ORM-free so they
unit-test with no DB, mirroring attribution.py / episodes.py / resistance.py.

The O4 safety-release SOP fires on EXACTLY one situation: a recipient-attached,
reported QNAT that is high (>= 10,000 IU/mL) OR symptomatic, with no release-event
logged inside the 24h window. The threshold, the window, and the symptomatic tiers
are NAMED CONSTANTS here (a discoverable module) so they can never be hard-coded
magic in a view nobody can find (AC2).

`SYMPTOMATIC_TIERS` is DERIVED from `episodes.SEVERITY_TIERS` (the single source of
truth for the Kotton-2018 tiers) so it can never drift from the episode deriver.
Timeliness is evaluated at DAY granularity — every date in the registry is a
`DateField` for the day-offset de-id contract (DEC); a same-day or next-day release
counts as timely (`0 <= released_offset - drawn_offset <= RELEASE_WINDOW_DAYS`).
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from .episodes import SEVERITY_TIERS

# QNAT at/above this IU/mL is a high-viral-load trigger (AC1). The boundary is
# inclusive (>=), so a draw exactly at 10,000 still requires a release.
RELEASE_THRESHOLD_IU_ML = Decimal("10000")
# The SOP deadline as the explicit named constant (AC2). Day-granular below.
RELEASE_WINDOW = timedelta(hours=24)
RELEASE_WINDOW_DAYS = RELEASE_WINDOW.days  # == 1; same-day/next-day entry is timely
# The symptomatic tiers, derived so they cannot drift from episodes.SEVERITY_TIERS
# (the SEVERITY_TIERS / RESISTANCE_LOCI precedent).
SYMPTOMATIC_TIERS = tuple(t for t in SEVERITY_TIERS if t != "asymptomatic")


def requires_release(value: Decimal | None, tier: str) -> bool:
    """A draw needs a logged release-event when it is high-viral-load OR
    symptomatic. A symptomatic draw triggers even with no recorded value; a
    sub-threshold asymptomatic draw never does."""
    if tier in SYMPTOMATIC_TIERS:
        return True
    return value is not None and value >= RELEASE_THRESHOLD_IU_ML


def is_release_timely(
    drawn_offset: int,
    released_offsets,
    window_days: int = RELEASE_WINDOW_DAYS,
) -> bool:
    """True iff ANY release lands inside the window — at/after the draw and no
    later than `window_days` after it. A release before the draw (negative delta)
    or no release at all (empty list) is never timely."""
    return any(0 <= offset - drawn_offset <= window_days for offset in released_offsets)
