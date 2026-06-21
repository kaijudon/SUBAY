"""Slice 07 — the PURE CMV-episode deriver.

No `django_db`, no ORM: every test runs against hand-built result series, which
is the structural guarantee behind AC1 (the deriver carries no DB dependency).

Topic #4 LOCKED rules exercised here:
- Start: first QNAT >= LoD (34.5 IU/mL).
- End:   first single QNAT < LoD (single-negative; NO two-negative rule).
- Recurrence: every <LoD -> >=LoD transition is a new episode; NO gap rule.
"""
from decimal import Decimal

from renova.registry.episodes import (
    LOD,
    Episode,
    EpisodePoint,
    derive_episodes,
    summarize_episodes,
)
from renova.registry.models import CMVQuantitative

POS = Decimal("1500")
NEG = Decimal("10")


def _series(*pairs):
    """Build EpisodePoints from (day, value) pairs (default severity)."""
    return [EpisodePoint(day, Decimal(value)) for day, value in pairs]


def test_lod_constant_matches_model_no_drift():
    """The one place the pure constant is cross-checked against the ORM model so
    the two can never silently diverge (import stays in the test, not the func)."""
    assert LOD == CMVQuantitative.LOD == Decimal("34.5")


def test_single_episode_opens_and_closes():
    eps = derive_episodes(_series((0, POS), (7, POS), (14, NEG)))
    assert eps == [Episode(episode_index=1, start_day=0, end_day=14, severity_tier="asymptomatic")]


def test_start_boundary_includes_exact_34_5():
    """AC2: the boundary is >= LoD, so the exact value 34.5 opens an episode."""
    eps = derive_episodes(_series((0, "34.5"), (7, NEG)))
    assert len(eps) == 1
    assert eps[0].start_day == 0


def test_just_below_lod_does_not_open():
    eps = derive_episodes(_series((0, "34.49"), (7, NEG)))
    assert eps == []


def test_single_negative_ends_episode_no_two_negative_rule():
    """AC3: a SINGLE sub-LoD result resolves the episode at its own day."""
    eps = derive_episodes(_series((0, POS), (10, NEG), (20, NEG)))
    assert len(eps) == 1
    assert eps[0].end_day == 10


def test_fluctuation_around_lod_is_multiple_episodes():
    """AC4: [>=, <, >=, <, >=] around 34.5 -> three distinct episodes."""
    eps = derive_episodes(
        _series((0, POS), (10, NEG), (20, POS), (30, NEG), (40, POS), (50, NEG))
    )
    assert [e.episode_index for e in eps] == [1, 2, 3]
    assert [(e.start_day, e.end_day) for e in eps] == [(0, 10), (20, 30), (40, 50)]


def test_post_resolution_positive_is_new_episode_no_gap_rule():
    """AC5: two positives split by one negative are two episodes regardless of the
    day gap — there is no minimum-gap merging."""
    eps = derive_episodes(_series((0, POS), (1, NEG), (365, POS), (400, NEG)))
    assert len(eps) == 2
    assert eps[0] == Episode(1, 0, 1, "asymptomatic")
    assert eps[1] == Episode(2, 365, 400, "asymptomatic")


def test_all_negative_series_yields_zero_episodes():
    """AC6."""
    assert derive_episodes(_series((0, NEG), (10, NEG), (20, NEG))) == []


def test_empty_series_yields_zero_episodes():
    assert derive_episodes([]) == []


def test_open_trailing_episode_has_no_end_day():
    """D-C: a series still >= LoD at its end is right-censored (end_day None)."""
    eps = derive_episodes(_series((0, POS), (7, POS)))
    assert len(eps) == 1
    assert eps[0].end_day is None


def test_episode_severity_is_max_tier_among_members():
    """AC7: the episode tier is the highest tier among its >=LoD members."""
    points = [
        EpisodePoint(0, POS, "asymptomatic"),
        EpisodePoint(7, POS, "disease"),
        EpisodePoint(14, POS, "syndrome"),
        EpisodePoint(21, NEG, "asymptomatic"),
    ]
    eps = derive_episodes(points)
    assert eps[0].severity_tier == "disease"


def test_severity_does_not_alter_pooled_boundaries():
    """AC7: two series differing ONLY in per-point severity produce byte-identical
    (index, start_day, end_day) tuples; only the episode tier differs."""
    base = [EpisodePoint(0, POS), EpisodePoint(10, NEG), EpisodePoint(20, POS)]
    loud = [
        EpisodePoint(0, POS, "disease"),
        EpisodePoint(10, NEG, "syndrome"),
        EpisodePoint(20, POS, "syndrome"),
    ]
    bare_boundaries = [(e.episode_index, e.start_day, e.end_day) for e in derive_episodes(base)]
    loud_eps = derive_episodes(loud)
    assert [(e.episode_index, e.start_day, e.end_day) for e in loud_eps] == bare_boundaries
    assert loud_eps[0].severity_tier == "disease"


# --- subject-level summary (AC8) ---


def test_summary_on_event_series():
    eps = derive_episodes(_series((30, POS), (60, NEG), (200, POS), (250, NEG)))
    s = summarize_episodes(eps, observation_start_day=0, observation_end_day=250)
    assert s.episode_count == 2
    assert s.any_episode_le_6mo is True  # first episode starts day 30 <= 180
    assert s.time_to_first_episode == 30
    assert s.time_to_first_censored is False
    assert s.person_time == 250


def test_summary_first_episode_after_6_months_is_not_le_6mo():
    eps = derive_episodes(_series((200, POS), (250, NEG)))
    s = summarize_episodes(eps, observation_start_day=0, observation_end_day=300)
    assert s.any_episode_le_6mo is False  # start day 200 > 180


def test_summary_all_negative_is_censored():
    """AC6/AC8: no episode -> count 0, not le_6mo, time-to-first censored at the
    last observed day, person-time spans the observed series."""
    s = summarize_episodes([], observation_start_day=0, observation_end_day=180)
    assert s.episode_count == 0
    assert s.any_episode_le_6mo is False
    assert s.time_to_first_episode == 180
    assert s.time_to_first_censored is True
    assert s.person_time == 180
