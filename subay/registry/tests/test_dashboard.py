"""Slice 16a (issue #20) - the dashboard T4 CONSORT-counts deriver, tested as a
pure function over fixtures the way test_scheduling.py / test_episodes.py test
their derivers. Asserts externally observable behavior (which bucket, what count,
full skeleton), not private helper shapes."""
from datetime import date

import pytest

from subay.registry.dashboard import consort_counts
from subay.registry.models import (
    RECIPIENT_COMPLETION_STATUS_CHOICES,
    Recipient,
)

SEVEN_LOCKED = [value for value, _ in RECIPIENT_COMPLETION_STATUS_CHOICES]


def _recipient(subject_id, status="enrolled"):
    return Recipient.objects.create(
        subject_id=subject_id,
        date_of_birth=date(1980, 1, 1),
        sex="M",
        kt_date=date(2025, 1, 1),
        completion_status=status,
    )


@pytest.mark.django_db
def test_consort_covers_all_seven_dispositions_in_prd_order():
    tile = consort_counts()
    assert [b.value for b in tile.buckets] == SEVEN_LOCKED


@pytest.mark.django_db
def test_empty_registry_renders_every_bucket_as_zero():
    tile = consort_counts()
    assert all(b.count == 0 for b in tile.buckets)
    assert tile.total == 0


@pytest.mark.django_db
def test_counts_group_by_disposition():
    _recipient("SCMVR01", "enrolled")
    _recipient("SCMVR02", "enrolled")
    _recipient("SCMVR03", "withdrawn")
    _recipient("SCMVR04", "completed")
    tile = consort_counts()
    by_value = {b.value: b.count for b in tile.buckets}
    assert by_value["enrolled"] == 2
    assert by_value["withdrawn"] == 1
    assert by_value["completed"] == 1
    assert tile.total == 4


@pytest.mark.django_db
def test_unpopulated_disposition_stays_zero_not_dropped():
    _recipient("SCMVR01", "enrolled")
    tile = consort_counts()
    by_value = {b.value: b.count for b in tile.buckets}
    # every non-enrolled disposition still present, reading 0
    assert by_value["died"] == 0
    assert by_value["graft_loss"] == 0
    assert by_value["missed_visit"] == 0
    assert len(tile.buckets) == len(SEVEN_LOCKED)


@pytest.mark.django_db
def test_total_equals_recipient_count_across_dispositions():
    _recipient("SCMVR01", "enrolled")
    _recipient("SCMVR02", "died")
    _recipient("SCMVR03", "lost_to_followup")
    tile = consort_counts()
    assert tile.total == Recipient.objects.count() == 3
