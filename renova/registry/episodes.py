"""Pure CMV-episode deriver (Slice 07) — ORM-free so it unit-tests with no DB.

A Data Analyst never hand-enters episode boundaries: they derive from the raw
QNAT series so they reproduce exactly from stored data and feed the SAP estimands.

Topic #4 LOCKED rules:
- Start: first QNAT >= LoD (34.5 IU/mL).
- End:   first single QNAT < LoD (single-negative; NO two-negative rule).
- Recurrence: every <LoD -> >=LoD transition is a new episode; NO gap rule.

Severity is a clinical, symptom-based tier (Kotton 2018). It is NOT a function of
the viral-load magnitude, so the deriver cannot compute it — it enters as a
per-point input. The episode's tier is the MAX tier among its >=LoD members and
never alters the pooled (index, start_day, end_day) boundaries.
"""
from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple

# Ascending clinical severity; list index is the rank used to pick the max tier.
SEVERITY_TIERS = ("asymptomatic", "syndrome", "disease")
LOD = Decimal("34.5")  # default; cross-checked == CMVQuantitative.LOD in the tests


class EpisodePoint(NamedTuple):
    """One reported QNAT result in day-offset space (transplant = day 0)."""

    day: int
    value: Decimal
    severity_tier: str = "asymptomatic"


class Episode(NamedTuple):
    episode_index: int  # not `index` — that shadows tuple.index (mypy override clash)
    start_day: int
    end_day: int | None  # None == open / right-censored (series ends still >= LoD)
    severity_tier: str


class EpisodeSummary(NamedTuple):
    episode_count: int
    any_episode_le_6mo: bool
    time_to_first_episode: int | None
    time_to_first_censored: bool
    person_time: int


def _max_tier(a: str, b: str) -> str:
    return a if SEVERITY_TIERS.index(a) >= SEVERITY_TIERS.index(b) else b


def derive_episodes(points, lod: Decimal = LOD) -> list[Episode]:
    """Ordered episodes from an already-chronological result series (single pass).

    `points` may be EpisodePoints or plain (day, value[, severity_tier]) tuples.
    """
    episodes: list[Episode] = []
    index = 0
    start_day: int | None = None
    tier = SEVERITY_TIERS[0]
    for raw in points:
        point = EpisodePoint(*raw)
        if point.value >= lod:
            if start_day is None:
                index += 1
                start_day = point.day
                tier = point.severity_tier
            else:
                tier = _max_tier(tier, point.severity_tier)
        elif start_day is not None:
            # First single sub-LoD result closes the open episode at its own day.
            episodes.append(Episode(index, start_day, point.day, tier))
            start_day = None
            tier = SEVERITY_TIERS[0]
    if start_day is not None:
        episodes.append(Episode(index, start_day, None, tier))
    return episodes


def summarize_episodes(
    episodes,
    observation_start_day: int,
    observation_end_day: int,
    horizon_days: int = 180,
) -> EpisodeSummary:
    """Subject-level variables feeding the SAP estimands. Person-time and the
    time-to-first censor anchor to the OBSERVED series span — never a fixed
    horizon — so sparse sampling can't manufacture unobserved follow-up."""
    person_time = observation_end_day - observation_start_day
    if not episodes:
        return EpisodeSummary(
            episode_count=0,
            any_episode_le_6mo=False,
            time_to_first_episode=observation_end_day,
            time_to_first_censored=True,
            person_time=person_time,
        )
    return EpisodeSummary(
        episode_count=len(episodes),
        any_episode_le_6mo=any(e.start_day <= horizon_days for e in episodes),
        time_to_first_episode=episodes[0].start_day,
        time_to_first_censored=False,
        person_time=person_time,
    )
