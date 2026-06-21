from datetime import date
from decimal import Decimal

import pytest

from renova.registry.episodes import Episode
from renova.registry.models import (
    CMVQuantitative,
    CMVSerology,
    Donor,
    Recipient,
    RecipientVisit,
)


@pytest.mark.django_db
def test_age_derived_at_kt_date():
    r = Recipient.objects.create(
        subject_id="SCMVR02", date_of_birth=date(1980, 6, 15), sex="M", kt_date=date(2025, 1, 1)
    )
    assert r.age == 44  # birthday not yet reached by 1 Jan 2025


@pytest.mark.parametrize(
    "donor,recip,expected",
    [
        ("POS", "NEG", "high"),  # D+/R-
        ("POS", "POS", "intermediate"),  # R+
        ("NEG", "POS", "intermediate"),  # R+
        ("NEG", "NEG", "low"),  # D-/R-
        (None, "NEG", None),  # incomplete -> undefined
    ],
)
def test_risk_stratum_from_serostatus(donor, recip, expected):
    r = Recipient(
        subject_id="SCMVR03",
        date_of_birth=date(1980, 1, 1),
        sex="M",
        kt_date=date(2025, 1, 1),
        donor_serostatus=donor,
        recipient_serostatus=recip,
    )
    assert r.risk_stratum == expected


# --- Slice 05: pre-KT IgG serostatus computed ONCE from the pre_kt assay ---


def _recipient(db, **kw):
    return Recipient.objects.create(
        subject_id="SCMVR05", date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=date(2025, 1, 1), **kw
    )


def _pre_kt_igg(recipient, value):
    v = RecipientVisit.objects.create(
        recipient=recipient, timepoint_label="pre_kt", actual_visit_date=date(2025, 1, 1)
    )
    CMVSerology.objects.create(
        recipient_visit=v, value=value, drawn_date=date(2025, 1, 1)
    )


@pytest.mark.django_db
def test_pre_kt_igg_serostatus_is_derived_not_stored():
    field_names = {f.name for f in Recipient._meta.get_fields()}
    assert "pre_kt_igg_serostatus" not in field_names
    assert isinstance(Recipient.pre_kt_igg_serostatus, property)


@pytest.mark.django_db
def test_pre_kt_igg_serostatus_positive():
    r = _recipient(None)
    _pre_kt_igg(r, Decimal("3.0"))  # >= 2.0 -> POS
    assert r.pre_kt_igg_serostatus == "POS"


@pytest.mark.django_db
def test_pre_kt_igg_serostatus_negative():
    r = _recipient(None)
    _pre_kt_igg(r, Decimal("1.0"))  # < 2.0 -> NEG
    assert r.pre_kt_igg_serostatus == "NEG"


@pytest.mark.django_db
def test_pre_kt_igg_serostatus_none_without_pre_kt_visit():
    r = _recipient(None)
    assert r.pre_kt_igg_serostatus is None


@pytest.mark.django_db
def test_pre_kt_igg_serostatus_none_when_igg_missing():
    r = _recipient(None)
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="pre_kt", actual_visit_date=date(2025, 1, 1)
    )
    CMVSerology.objects.create(
        recipient_visit=v, result_status="missing", drawn_date=date(2025, 1, 1)
    )
    assert r.pre_kt_igg_serostatus is None


@pytest.mark.django_db
def test_pre_kt_igg_serostatus_equals_the_igg_derivation_one_canonical_value():
    """AC3: the value stratification (Obj 4a) and attribution (Obj 5) would each
    read is the SAME single canonical derivation off the pre_kt IgG result."""
    r = _recipient(None)
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="pre_kt", actual_visit_date=date(2025, 1, 1)
    )
    s = CMVSerology.objects.create(
        recipient_visit=v, value=Decimal("5.0"), drawn_date=date(2025, 1, 1)
    )
    derived = "POS" if s.is_positive else "NEG"
    assert r.pre_kt_igg_serostatus == derived


# --- Slice 07: CMV episodes derived from the reported QNAT series (ORM surface) ---

POS = Decimal("1500")
NEG = Decimal("10")


def _qnat(visit, value, drawn_date, **kw):
    return CMVQuantitative.objects.create(
        recipient_visit=visit, value=value, drawn_date=drawn_date, **kw
    )


@pytest.mark.django_db
def test_cmv_episodes_is_a_property_not_stored():
    """Episodes are computed at read, never a stored field (derive-don't-store)."""
    field_names = {f.name for f in Recipient._meta.get_fields()}
    assert "cmv_episodes" not in field_names
    assert isinstance(Recipient.cmv_episodes, property)


@pytest.mark.django_db
def test_cmv_episodes_built_from_reported_qnat_across_visits():
    r = _recipient(None)
    v1 = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8)
    )
    v2 = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_180", actual_visit_date=date(2025, 7, 20)
    )
    _qnat(v1, POS, date(2025, 1, 1))   # day 0  -> opens episode 1
    _qnat(v1, NEG, date(2025, 1, 11))  # day 10 -> closes episode 1
    _qnat(v2, POS, date(2025, 7, 20))  # day 200 -> opens episode 2 (open, end None)

    assert r.cmv_episodes == [
        Episode(1, 0, 10, "asymptomatic"),
        Episode(2, 200, None, "asymptomatic"),
    ]


@pytest.mark.django_db
def test_cmv_episodes_excludes_missing_observations():
    """D-B: a mid-episode QC failure (result_status='missing') is NOT clearance, so
    it never spuriously ends an open episode."""
    r = _recipient(None)
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8)
    )
    _qnat(v, POS, date(2025, 1, 1))                       # day 0  open
    _qnat(v, None, date(2025, 1, 6), result_status="missing")  # day 5  ignored
    _qnat(v, POS, date(2025, 1, 11))                     # day 10 still open
    _qnat(v, NEG, date(2025, 1, 21))                     # day 20 close

    assert r.cmv_episodes == [Episode(1, 0, 20, "asymptomatic")]


@pytest.mark.django_db
def test_cmv_episodes_excludes_donor_attached_qnat():
    """Donor QNAT has no kt anchor -> never an episode in the recipient series."""
    d = Donor.objects.create(
        subject_id="DCMVD07", date_of_birth=date(1975, 1, 1), sex="F"
    )
    CMVQuantitative.objects.create(donor=d, value=POS, drawn_date=date(2024, 12, 1))
    r = _recipient(None)
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8)
    )
    _qnat(v, NEG, date(2025, 1, 1))  # recipient never crosses LoD

    assert r.cmv_episodes == []


@pytest.mark.django_db
def test_cmv_episode_tier_is_max_among_members():
    r = _recipient(None)
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8)
    )
    _qnat(v, POS, date(2025, 1, 1), severity_tier="asymptomatic")
    _qnat(v, POS, date(2025, 1, 11), severity_tier="disease")
    _qnat(v, NEG, date(2025, 1, 21))

    assert r.cmv_episodes[0].severity_tier == "disease"


@pytest.mark.django_db
def test_cmv_episode_summary_matches_pure_result():
    from renova.registry.episodes import summarize_episodes

    r = _recipient(None)
    v = RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=date(2025, 1, 8)
    )
    _qnat(v, POS, date(2025, 1, 1))   # day 0
    _qnat(v, NEG, date(2025, 1, 31))  # day 30

    expected = summarize_episodes(
        r.cmv_episodes, observation_start_day=0, observation_end_day=30
    )
    assert r.cmv_episode_summary == expected
    assert r.cmv_episode_summary.episode_count == 1
    assert r.cmv_episode_summary.person_time == 30


@pytest.mark.django_db
def test_cmv_episode_summary_none_without_reported_qnat():
    r = _recipient(None)
    assert r.cmv_episode_summary is None
