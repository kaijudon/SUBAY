import pytest
from django.contrib.auth.models import Group


@pytest.mark.django_db
def test_four_role_groups_exist():
    names = set(Group.objects.values_list("name", flat=True))
    assert {"data_entry", "adjudicator", "analyst-readonly", "admin"} <= names
