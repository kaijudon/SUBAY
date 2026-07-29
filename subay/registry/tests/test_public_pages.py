"""The unauthenticated surface: landing, protocol summary, and the sign-in screen.

The load-bearing tests here are the leak tests. Everything else on these pages is
presentation, but a subject identifier or a calendar date rendered to an
anonymous request would be a disclosure the export chokepoint never sees, so
those get explicit assertions rather than being inferred from "the page rendered".
"""
import datetime

import pytest
from django.urls import reverse

from subay.registry import safety
from subay.registry.models import (
    CMVQuantitative,
    CMVSerology,
    Recipient,
    RecipientVisit,
    VISIT_SHIFT_CAP_DAYS,
)
from subay.registry.scheduling import TIMEPOINT_OFFSETS
from subay.registry.views_public import TARGET_RECIPIENTS


@pytest.fixture
def recipient(db):
    return Recipient.objects.create(
        subject_id="SCMVR07",
        kt_date=datetime.date(2026, 1, 5),
        date_of_birth=datetime.date(1978, 3, 14),
        donor_serostatus="POS",
        recipient_serostatus="NEG",
    )


# --------------------------------------------------------------- reachability


@pytest.mark.django_db
def test_landing_is_reachable_without_authentication(client):
    response = client.get(reverse("public:landing"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_protocol_is_reachable_without_authentication(client):
    response = client.get(reverse("public:protocol"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_landing_links_to_the_admin_login(client):
    response = client.get(reverse("public:landing"))
    assert reverse("admin:login").encode() in response.content


# ------------------------------------------------------------------- leakage


@pytest.mark.django_db
def test_landing_never_renders_a_subject_id(client, recipient):
    """The register having rows must not put any of them on the front door."""
    response = client.get(reverse("public:landing"))
    assert recipient.subject_id.encode() not in response.content


@pytest.mark.django_db
def test_protocol_never_renders_a_subject_id(client, recipient):
    response = client.get(reverse("public:protocol"))
    assert recipient.subject_id.encode() not in response.content


@pytest.mark.django_db
def test_public_pages_never_render_a_calendar_date_from_the_register(client, recipient):
    """kt_date is the day-0 anchor; it is the exact shape of value the export
    contract forbids leaving the system. Neither page may render one."""
    for name in ("public:landing", "public:protocol"):
        body = client.get(reverse(name)).content
        assert recipient.kt_date.isoformat().encode() not in body
        assert recipient.date_of_birth.isoformat().encode() not in body


# ----------------------------------------------------------- derived figures


@pytest.mark.django_db
def test_landing_counters_follow_the_register(client, recipient):
    """The counters are aggregates, so they must move when the register does —
    a hardcoded number would be a stored fact that drifts."""
    RecipientVisit.objects.create(
        recipient=recipient,
        timepoint_label="pre_kt",
        actual_visit_date=recipient.kt_date,
    )
    context = client.get(reverse("public:landing")).context
    counters = {stat["label"]: stat["n"] for stat in context["stats"]}
    assert counters[f"recipients on the register · of {TARGET_RECIPIENTS} at target"] == 1
    assert counters["recipient visits captured on the spine"] == 1
    assert counters["identifiers in the analysis set"] == 0


@pytest.mark.django_db
def test_protocol_spine_matches_the_scheduling_module(client):
    """The rendered spine is the scheduling module's spine, in day order — not a
    second copy of it that can fall behind."""
    spine = client.get(reverse("public:protocol")).context["spine"]
    assert [row["timepoint"] for row in spine] == sorted(
        TIMEPOINT_OFFSETS, key=TIMEPOINT_OFFSETS.get
    )
    assert [row["offset"] for row in spine] == sorted(TIMEPOINT_OFFSETS.values())
    assert all(str(VISIT_SHIFT_CAP_DAYS) in row["window"] for row in spine)


@pytest.mark.django_db
def test_protocol_quotes_the_real_assay_constants(client):
    """Every threshold on the page is read from the constant that enforces it,
    so the page cannot claim a cutoff the software does not apply."""
    body = client.get(reverse("public:protocol")).content.decode()
    assert str(CMVQuantitative.LOD) in body
    assert CMVQuantitative.ASSAY in body
    assert str(CMVSerology.POSITIVE_THRESHOLD) in body
    assert f"{safety.RELEASE_THRESHOLD_IU_ML:,.0f}" in body
    assert str(int(safety.RELEASE_WINDOW.total_seconds() // 3600)) in body


@pytest.mark.django_db
def test_protocol_counts_recipients_by_derived_risk_stratum(client, recipient):
    """D+/R− is high risk, and a recipient missing either serostatus stays
    undetermined rather than being guessed into a bucket."""
    Recipient.objects.create(
        subject_id="SCMVR08",
        kt_date=datetime.date(2026, 2, 1),
        date_of_birth=datetime.date(1969, 8, 2),
        donor_serostatus=None,
        recipient_serostatus=None,
    )
    strata = {
        row["key"]: row["n"]
        for row in client.get(reverse("public:protocol")).context["strata"]
    }
    assert strata == {"high": 1, "intermediate": 0, "low": 0, "none": 1}


@pytest.mark.django_db
def test_protocol_renders_every_timepoint_with_a_collection_list(client):
    """A timepoint added to TIMEPOINT_OFFSETS without a collection entry must
    fail loudly here rather than render a blank cell in production."""
    spine = client.get(reverse("public:protocol")).context["spine"]
    assert all(row["collected"] for row in spine)


# ------------------------------------------------------------------ sign-in


@pytest.mark.django_db
def test_login_uses_the_subay_split_panel_template(client):
    response = client.get(reverse("admin:login"))
    assert response.status_code == 200
    assert "admin/subay_login.html" in [t.name for t in response.templates]


@pytest.mark.django_db
def test_login_solicits_credentials_and_the_otp_token_on_one_screen(client):
    """django-otp's admin form carries all three fields in one request; the
    template must render each of them or a user cannot complete a sign-in."""
    body = client.get(reverse("admin:login")).content.decode()
    for field_id in ("id_username", "id_password", "id_otp_token"):
        assert field_id in body


@pytest.mark.django_db
def test_login_offers_a_way_back_to_the_landing_page(client):
    body = client.get(reverse("admin:login")).content.decode()
    assert reverse("public:landing") in body
