from datetime import date

import pytest

from subay.registry.models import Recipient


@pytest.mark.django_db
def test_simple_history_records_create_and_update():
    r = Recipient.objects.create(
        subject_id="SCMVR04", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    assert r.history.count() == 1  # create logged
    r.sex = "F"
    r.save()
    assert r.history.count() == 2  # update logged
