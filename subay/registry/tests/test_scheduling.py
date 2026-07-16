"""AC4 — the closure-shift deep module, unit-tested in isolation (no DB).

`first_operating_day` is the load-bearing unit. It takes a nominal date and a
calendar of closure days (each knowing whether it closes clinic, lab, or both)
and returns the first day BOTH clinic and lab operate, on or after nominal.
Forward only — a multi-day stretch collapses to ONE shift, never backward,
never partial.
"""
from datetime import date

from subay.registry.scheduling import (
    TIMEPOINT_OFFSETS,
    ClosureDayLike,
    first_operating_day,
)


def _closure(d, closes_clinic=True, closes_lab=True):
    return ClosureDayLike(date=d, closes_clinic=closes_clinic, closes_lab=closes_lab)


def test_no_closure_returns_nominal_unchanged():
    nominal = date(2025, 1, 8)
    assert first_operating_day(nominal, []) == nominal


def test_single_closure_shifts_forward_one_day():
    nominal = date(2025, 1, 8)
    closures = [_closure(date(2025, 1, 8))]
    assert first_operating_day(nominal, closures) == date(2025, 1, 9)


def test_multi_day_stretch_is_exactly_one_forward_shift():
    """3 consecutive closure days -> the 4th day, not three separate hops."""
    nominal = date(2025, 1, 8)
    closures = [
        _closure(date(2025, 1, 8)),
        _closure(date(2025, 1, 9)),
        _closure(date(2025, 1, 10)),
    ]
    assert first_operating_day(nominal, closures) == date(2025, 1, 11)


def test_lab_only_closure_still_forces_shift():
    """A day that closes only the lab still blocks the visit (needs BOTH)."""
    nominal = date(2025, 1, 8)
    closures = [_closure(date(2025, 1, 8), closes_clinic=False, closes_lab=True)]
    assert first_operating_day(nominal, closures) == date(2025, 1, 9)


def test_clinic_only_closure_still_forces_shift():
    nominal = date(2025, 1, 8)
    closures = [_closure(date(2025, 1, 8), closes_clinic=True, closes_lab=False)]
    assert first_operating_day(nominal, closures) == date(2025, 1, 9)


def test_never_shifts_backward():
    """A closure BEFORE the nominal day is irrelevant — no backward movement."""
    nominal = date(2025, 1, 8)
    closures = [_closure(date(2025, 1, 7)), _closure(date(2025, 1, 6))]
    assert first_operating_day(nominal, closures) == nominal


def test_six_protocol_offsets_present():
    assert TIMEPOINT_OFFSETS == {
        "pre_kt": 0,
        "day_7": 7,
        "day_30": 30,
        "day_90": 90,
        "day_120": 120,
        "day_180": 180,
    }
