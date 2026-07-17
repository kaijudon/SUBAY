"""Closure-shift scheduling — the load-bearing deep module (PRD lines 208/219).

Pure, DB-free: given a nominal protocol day and a calendar of closure days, return
the first day BOTH clinic and lab operate. Forward only — consecutive closures
collapse into one stretch (a single forward shift), never backward, never partial.

Kept here as plain functions over `date` so it is unit-testable in isolation,
never on a model's private internals.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

# The six recipient protocol timepoints and their day-offset from kt_date
# (transplant = day 0). pre_kt is the at-transplant serostatus draw (DEC-010).
TIMEPOINT_OFFSETS: dict[str, int] = {
    "pre_kt": 0,
    "day_7": 7,
    "day_30": 30,
    "day_90": 90,
    "day_120": 120,
    "day_180": 180,
}

# Dashboard T1 (issue #16) look-ahead horizon: a synthesized visit gap whose
# closure-shifted expected date falls within this many days of today is surfaced
# as "due-soon". A single named constant so widening/narrowing the window is a
# one-line, discoverable edit - it lives beside the timepoint offsets it works over.
VISIT_DUE_HORIZON_DAYS: int = 7


@dataclass(frozen=True)
class ClosureDayLike:
    """A closure-day record as the shift function needs it. The real `ClosureDay`
    model duck-types this; tests pass plain instances with no DB."""

    date: date
    closes_clinic: bool = True
    closes_lab: bool = True


def _is_closed(day: date, closures: Iterable[ClosureDayLike]) -> bool:
    """A day is unusable if any closure on it shuts EITHER clinic or lab — the
    visit needs BOTH operating."""
    for c in closures:
        if c.date == day and (c.closes_clinic or c.closes_lab):
            return True
    return False


def first_operating_day(nominal_date: date, closures: Iterable[ClosureDayLike]) -> date:
    """First day on or after `nominal_date` that clinic and lab both operate.

    Forward only: a multi-day closure stretch yields exactly one shift to the day
    past the stretch. Never returns a date before `nominal_date`.
    """
    closures = list(closures)
    day = nominal_date
    while _is_closed(day, closures):
        day += timedelta(days=1)
    return day
