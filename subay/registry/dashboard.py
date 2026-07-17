"""Admin landing dashboard derivers (issue #16, slice 16a onward).

Pure, per-tile functions - one per dashboard tile - each returning a small
structure the admin index override drops straight into template context. No tile
logic lives in the view or the template, mirroring how `scheduling.py`,
`episodes.py`, and `safety.py` isolate their logic as unit-testable units.

Every tile is DERIVED: computed on request from stored facts, never stored
(derive-don't-store). The dashboard is inside the PHI boundary (authenticated
staff only), so on-screen tiles may carry live Subject IDs and calendar dates;
the de-identification contract binds only the export chokepoint, which this
module never touches and adds no column to.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Count

from .models import RECIPIENT_COMPLETION_STATUS_CHOICES, Recipient
from .scheduling import (
    TIMEPOINT_OFFSETS,
    VISIT_DUE_HORIZON_DAYS,
    first_operating_day,
)

# Bucket keys for T1, ordered most-actionable first for stable display.
DUE_SOON = "due_soon"
OVERDUE = "overdue"
MISSED = "missed"
BUCKET_ORDER = [OVERDUE, DUE_SOON, MISSED]


@dataclass(frozen=True)
class DispositionBucket:
    """One CONSORT disposition and its recipient count."""

    value: str   # raw completion_status value, e.g. "enrolled"
    label: str   # human label, e.g. "Enrolled"
    count: int


@dataclass(frozen=True)
class Tile:
    """A grouped-count tile (T4). `key` names the tile for template ids/anchors;
    `icon` is a shipped `.ico-*` modifier class (no new asset). `kind` lets the
    template branch on the tile shape."""

    key: str
    title: str
    icon: str
    buckets: list
    total: int
    kind: str = "consort"


@dataclass(frozen=True)
class CountTile:
    """A single-count operational tile (T2/T3): one number plus a deep-link to the
    worklist it summarizes. The count is taken from that worklist's own queryset,
    so tile and worklist can never disagree."""

    key: str
    title: str
    icon: str
    count: int
    link: str        # resolved worklist URL
    link_label: str
    kind: str = "count"


@dataclass(frozen=True)
class ScheduleGap:
    """One synthesized expected-but-absent visit. Carries the live Subject ID and
    timepoint (inside the PHI boundary) plus a deep-link to the pre-filled visit
    add-form. Read-only: T1 writes nothing and creates no row."""

    subject_id: str
    timepoint_label: str
    expected_date: date
    bucket: str          # DUE_SOON | OVERDUE | MISSED
    add_url: str


@dataclass(frozen=True)
class ScheduleTile:
    """T1 - visits due/overdue. `gaps` are the surfaced items; `counts` is the
    per-bucket tally for the tile summary."""

    key: str
    title: str
    icon: str
    gaps: list
    counts: dict
    total: int
    kind: str = "schedule"


def consort_counts(recipients=None):
    """T4 - recipient counts grouped by patient-level `completion_status`, the
    CONSORT disposition skeleton.

    Returns every one of the seven LOCKED disposition values in PRD order,
    zero-count buckets included, so the tile always renders the full skeleton and
    a bucket reading 0 is a stated fact, not a missing row. `recipients` lets a
    test pass an explicit queryset; production calls it with no argument and
    counts every recipient.
    """
    qs = Recipient.objects.all() if recipients is None else recipients
    tallied = {
        row["completion_status"]: row["n"]
        for row in qs.values("completion_status").annotate(n=Count("pk"))
    }
    buckets = [
        DispositionBucket(value=value, label=label, count=tallied.get(value, 0))
        for value, label in RECIPIENT_COMPLETION_STATUS_CHOICES
    ]
    return Tile(
        key="consort",
        title="Study progress (CONSORT)",
        icon="ico-team",
        buckets=buckets,
        total=sum(b.count for b in buckets),
    )


def unverified_count():
    """T2 - count of entered-but-unverified outcome-critical rows.

    Iterates the SAME per-model `is_verified=False` queryset the verification
    worklist iterates (`OUTCOME_CRITICAL`, sourced from sites.py so there is one
    definition), so the tile count is definitionally the worklist's row count and
    the two can never disagree. Links to that worklist.
    """
    from django.apps import apps
    from django.urls import reverse

    from .sites import OUTCOME_CRITICAL

    count = sum(
        apps.get_model("registry", label).objects.filter(is_verified=False).count()
        for label in OUTCOME_CRITICAL
    )
    return CountTile(
        key="unverified",
        title="Unverified outcome-critical",
        icon="ico-shield",
        count=count,
        link=reverse("admin:verification_worklist"),
        link_label="Open verification worklist",
    )


def release_overdue_count():
    """T3 - count of QNAT rows flagged release-overdue.

    Uses the standing `overdue_release_flags()` queryset the safety worklist uses,
    so the safety threshold and window stay sourced from safety.py's named
    constants (never re-inlined here) and the count matches the worklist row for
    row. Links to that worklist.
    """
    from django.apps import apps
    from django.urls import reverse

    model = apps.get_model("registry", "cmvquantitative")
    # overdue_release_flags() returns a materialized list (post-query flag
    # evaluation), the same object the safety worklist iterates - so len() here is
    # exactly that worklist's row count.
    return CountTile(
        key="release_overdue",
        title="Release-overdue QNAT",
        icon="ico-alarm",
        count=len(model.objects.overdue_release_flags()),
        link=reverse("admin:safety_worklist"),
        link_label="Open release-timeliness worklist",
    )


def visits_due(today=None):
    """T1 - synthesize the six-timepoint schedule per still-enrolled recipient,
    closure-shift each nominal day, and surface only the expected timepoints that
    have NO visit row yet (the gaps). An entered visit is never shown.

    Buckets each gap against `today`:
      - due_soon: the closure-shifted expected date is today or later and within
        the look-ahead horizon (`VISIT_DUE_HORIZON_DAYS`); a farther-out gap is not
        surfaced yet.
      - overdue: the expected date has passed but today is still within the +3-day
        cap from the NOMINAL day, so the draw can still be recorded as an on-time
        visit (the cap is measured from nominal, matching RecipientVisit.clean()).
      - missed: today is past the +3-day cap; the action is to record the visit as
        completion_status='missed_visit'.

    Enrolled-only: only patient-level completion_status == 'enrolled' generates
    expectations, so a withdrawn/died/lost/graft-loss/completed/patient-missed
    recipient produces nothing (no phantom overdue on a closed timeline). A single
    visit-level missed_visit does not change the patient-level disposition, so such
    a recipient stays enrolled and their remaining timeline still surfaces.

    Pure read: creates no row and writes nothing; the two same-named
    completion_status fields are only ever read here.
    """
    from django.urls import reverse

    from .models import VISIT_SHIFT_CAP_DAYS, ClosureDay

    today = today or date.today()
    horizon = timedelta(days=VISIT_DUE_HORIZON_DAYS)
    cap = timedelta(days=VISIT_SHIFT_CAP_DAYS)
    closures = list(ClosureDay.objects.all())
    add_base = reverse("admin:registry_recipientvisit_add")

    gaps = []
    enrolled = Recipient.objects.filter(completion_status="enrolled").prefetch_related("visits")
    for recipient in enrolled:
        entered = {v.timepoint_label for v in recipient.visits.all()}
        for label, offset in TIMEPOINT_OFFSETS.items():
            if label in entered:
                continue  # a recorded visit is never a gap
            nominal = recipient.kt_date + timedelta(days=offset)
            expected = first_operating_day(nominal, closures)
            if expected >= today:
                if expected > today + horizon:
                    continue  # too far out to surface yet
                bucket = DUE_SOON
            elif today <= nominal + cap:
                bucket = OVERDUE
            else:
                bucket = MISSED
            add_url = (
                f"{add_base}?recipient={recipient.pk}"
                f"&timepoint_label={label}"
                f"&actual_visit_date={expected.isoformat()}"
            )
            gaps.append(ScheduleGap(
                subject_id=recipient.subject_id,
                timepoint_label=label,
                expected_date=expected,
                bucket=bucket,
                add_url=add_url,
            ))

    gaps.sort(key=lambda g: (BUCKET_ORDER.index(g.bucket), g.expected_date, g.subject_id))
    counts = {b: sum(1 for g in gaps if g.bucket == b) for b in BUCKET_ORDER}
    return ScheduleTile(
        key="visits_due",
        title="Visits due / overdue",
        icon="ico-calendar",
        gaps=gaps,
        counts=counts,
        total=len(gaps),
    )
