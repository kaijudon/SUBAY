from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from subay.registry.models import BaseSubject, Recipient


@pytest.mark.django_db
def test_basesubject_is_abstract_and_emits_no_table():
    assert BaseSubject._meta.abstract is True
    assert "registry_basesubject" not in connection.introspection.table_names()


@pytest.mark.django_db
def test_subject_id_stored_as_string_leading_zero_preserved():
    Recipient.objects.create(
        subject_id="SCMVR07", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1)
    )
    fetched = Recipient.objects.get(pk="SCMVR07")
    assert isinstance(fetched.subject_id, str)
    assert fetched.subject_id == "SCMVR07"  # never coerced to 7


def test_subject_id_validator_rejects_bad_format():
    r = Recipient(subject_id="123", date_of_birth=date(1980, 1, 1), sex="M", kt_date=date(2025, 1, 1))
    with pytest.raises(ValidationError):
        r.full_clean()
