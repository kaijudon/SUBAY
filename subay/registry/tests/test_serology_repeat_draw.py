"""Slice 17 ticket 06 - an equivocal result becomes a task somebody can see.

The PI ruled that a grayzone reading is a direction to draw again, not a
serostatus. Ticket 02 made SUBAY stop rounding it into an answer, which is the
correctness half. This is the operational half: a draw with an unresolved
grayzone has to surface somewhere a clinician looks, and leave that surface only
when a repeat has actually been drawn.

The load-bearing property, the same one T2 and T3 already hold: the tile count
comes from the worklist's OWN queryset, so the two can never disagree.

Donors are deliberately excluded throughout. A donor holds at most one serology
by DB constraint and is frequently deceased, so an equivocal donor result is
terminal rather than pending. Letting one into the worklist would park a row
nobody can ever discharge.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from subay.registry.dashboard import awaiting_repeat_count
from subay.registry.models import CMVSerology, Donor, DonorVisit, Recipient, RecipientVisit
from subay.registry.serology_ranges import (
    ADVISORY_EFFECTIVE,
    GEN1,
    GEN2_IGG_EQUIVOCAL_FROM_AU_ML,
    GEN2_IGG_REACTIVE_FROM_AU_ML,
    GEN2_IGM_EQUIVOCAL_FROM_AU_ML,
)

DRAWN = ADVISORY_EFFECTIVE  # 2nd generation, so the grayzone exists at all
EQUIVOCAL_IGG = GEN2_IGG_EQUIVOCAL_FROM_AU_ML          # 0.80, lower edge, inclusive
REACTIVE_IGG = GEN2_IGG_REACTIVE_FROM_AU_ML            # 1.20
EQUIVOCAL_IGM = GEN2_IGM_EQUIVOCAL_FROM_AU_ML          # 2.00


# --- fixtures --------------------------------------------------------------

def _recipient(subject_id="SCMVR31"):
    return Recipient.objects.create(
        subject_id=subject_id, date_of_birth=date(1980, 1, 1), sex="M", kt_date=DRAWN
    )


def _visit(recipient, timepoint_label="pre_kt"):
    return RecipientVisit.objects.create(
        recipient=recipient, timepoint_label=timepoint_label, actual_visit_date=DRAWN
    )


def _serology(visit, igg=EQUIVOCAL_IGG, **kw):
    return CMVSerology.objects.create(
        recipient_visit=visit, value=Decimal(igg), drawn_date=DRAWN, **kw
    )


def _donor_serology(subject_id="DCMVD31", igg=EQUIVOCAL_IGG):
    donor = Donor.objects.create(
        subject_id=subject_id, date_of_birth=date(1975, 1, 1), sex="F",
        donor_type="living",
    )
    DonorVisit.objects.create(donor=donor, draw_date=DRAWN)
    return CMVSerology.objects.create(
        donor=donor, value=Decimal(igg), drawn_date=DRAWN
    )


# --- the predicate ---------------------------------------------------------

def test_an_equivocal_igg_draw_is_awaiting_a_repeat(db):
    s = _serology(_visit(_recipient()))
    assert s.is_equivocal
    assert s.awaiting_repeat


def test_an_equivocal_igm_alone_is_enough(db):
    """Either channel. A clean IgG does not make an indeterminate IgM resolved -
    the draw as a whole still has an unanswered question on it."""
    s = _serology(
        _visit(_recipient()),
        igg=REACTIVE_IGG,
        igm_value=Decimal(EQUIVOCAL_IGM),
        igm_status="reported",
    )
    assert s.igg_interpretation == "reactive"
    assert s.igm_interpretation == "equivocal"
    assert s.awaiting_repeat


def test_a_clean_draw_is_not_awaiting_a_repeat(db):
    s = _serology(_visit(_recipient()), igg=REACTIVE_IGG)
    assert not s.is_equivocal
    assert not s.awaiting_repeat


def test_a_first_generation_draw_can_never_await_a_repeat(db):
    """1st-generation reagent has ONE cutoff and no grayzone (DEC-016), so a
    pre-advisory row is structurally incapable of entering the worklist. Worth a
    test by name: the band map expresses that as a zero-width band rather than as
    a separate code path, which is easy to break silently."""
    s = _serology(_visit(_recipient()), reagent_generation=GEN1)
    assert s.igg_interpretation in ("non_reactive", "reactive")
    assert not s.is_equivocal
    assert not s.awaiting_repeat


def test_a_repeated_draw_leaves_the_worklist(db):
    visit = _visit(_recipient())
    first = _serology(visit)
    _serology(visit, igg=REACTIVE_IGG, repeats=first)

    first.refresh_from_db()
    assert first.is_equivocal        # the frozen lab fact is never edited away
    assert not first.awaiting_repeat  # but the question has been answered


def test_a_repeat_that_is_itself_equivocal_takes_its_place(db):
    """Repeating a draw once does not close the question out. Exactly one row is
    pending at any time along the chain, and it is always the newest."""
    visit = _visit(_recipient())
    first = _serology(visit)
    second = _serology(visit, repeats=first)

    first.refresh_from_db()
    assert not first.awaiting_repeat
    assert second.awaiting_repeat
    assert [s.pk for s in CMVSerology.objects.awaiting_repeat()] == [second.pk]


# --- donors are excluded ---------------------------------------------------

def test_an_equivocal_donor_result_never_appears_in_the_count(db):
    """A donor result is terminal, not pending: one serology per donor by
    constraint, and a deceased donor cannot be drawn again. It would sit in the
    worklist forever with no action able to discharge it."""
    donor_row = _donor_serology()
    assert donor_row.is_equivocal      # it IS grayzone
    assert not donor_row.awaiting_repeat  # and still not a task
    assert CMVSerology.objects.awaiting_repeat() == []
    assert awaiting_repeat_count().count == 0


def test_the_one_serology_per_donor_constraint_is_unchanged(db):
    """Relaxing it to let a donor be re-drawn was considered and rejected."""
    first = _donor_serology()
    with pytest.raises(IntegrityError), transaction.atomic():
        CMVSerology.objects.create(
            donor=first.donor, value=Decimal(REACTIVE_IGG), drawn_date=DRAWN
        )


# --- the repeat pointer's own rules ---------------------------------------

def test_a_draw_cannot_repeat_itself_in_the_database(db):
    """A cycle of length one would discharge a draw from the worklist using the
    draw itself as the resolution. The one repeat rule a single-row
    CheckConstraint can express, so it is enforced on the bare-save path too."""
    s = _serology(_visit(_recipient()))
    with pytest.raises(IntegrityError), transaction.atomic():
        CMVSerology.objects.filter(pk=s.pk).update(repeats=s.pk)
    s.refresh_from_db()
    assert s.repeats_id is None
    assert s.awaiting_repeat


def test_a_repeat_must_be_the_same_subject(db):
    one = _serology(_visit(_recipient("SCMVR31")))
    other_visit = _visit(_recipient("SCMVR32"))
    candidate = CMVSerology(
        recipient_visit=other_visit, value=Decimal(REACTIVE_IGG),
        drawn_date=DRAWN, repeats=one,
    )
    with pytest.raises(ValidationError) as exc:
        candidate.full_clean()
    assert "repeats" in exc.value.message_dict


def test_a_repeat_must_point_at_a_grayzone_draw(db):
    """Pointing at a clean result would claim a repeat was directed when it was
    not, and would put a pair in the record that no clinician ordered."""
    visit = _visit(_recipient())
    clean = _serology(visit, igg=REACTIVE_IGG)
    candidate = CMVSerology(
        recipient_visit=visit, value=Decimal(REACTIVE_IGG),
        drawn_date=DRAWN, repeats=clean,
    )
    with pytest.raises(ValidationError) as exc:
        candidate.full_clean()
    assert "not equivocal" in " ".join(exc.value.message_dict["repeats"])


def test_a_donor_draw_cannot_be_repeated(db):
    donor_row = _donor_serology()
    visit = _visit(_recipient())
    candidate = CMVSerology(
        recipient_visit=visit, value=Decimal(REACTIVE_IGG),
        drawn_date=DRAWN, repeats=donor_row,
    )
    with pytest.raises(ValidationError) as exc:
        candidate.full_clean()
    assert "repeats" in exc.value.message_dict


def test_an_ordinary_draw_needs_no_repeat_pointer(db):
    """The overwhelming majority of results repeat nothing, so the guard must
    leave the ordinary entry path completely alone."""
    visit = _visit(_recipient())
    CMVSerology(
        recipient_visit=visit, value=Decimal(REACTIVE_IGG), drawn_date=DRAWN
    ).full_clean()  # must not raise


# --- the queryset ----------------------------------------------------------

def test_the_queryset_is_empty_when_nothing_is_pending(db):
    _serology(_visit(_recipient()), igg=REACTIVE_IGG)
    assert CMVSerology.objects.awaiting_repeat() == []
    assert awaiting_repeat_count().count == 0


def test_the_tile_reads_the_worklist_queryset(db):
    visit = _visit(_recipient())
    _serology(visit)
    _serology(_visit(_recipient("SCMVR32")))
    _donor_serology()  # equivocal, must not be counted

    tile = awaiting_repeat_count()
    assert tile.key == "awaiting_repeat"
    assert tile.count == len(CMVSerology.objects.awaiting_repeat()) == 2
    assert tile.link == reverse("admin:serology_repeat_worklist")


# --- RBAC and tile-versus-worklist agreement through the admin client ------

def _otp_client(user):
    device = TOTPDevice.objects.create(user=user, name="test", confirmed=True)
    client = Client()
    client.force_login(user)
    session = client.session
    session["otp_device_id"] = device.persistent_id
    session.save()
    return client


def _group_user(username, group_name):
    user = User.objects.create_user(username, f"{username}@x", "pw", is_staff=True)
    user.groups.add(Group.objects.get(name=group_name))
    return user


def test_the_data_manager_sees_the_repeat_tile(db):
    client = _otp_client(_group_user("dm", "data_manager"))
    resp = client.get(reverse("admin:index"))
    assert "awaiting_repeat" in [t.key for t in resp.context["dashboard_tiles"]]


def test_the_view_only_analyst_sees_neither_tile_nor_worklist(db):
    """The gate is change-on-serology, the permission that lets a user record the
    repeat. An analyst can read a result but cannot discharge one of these, so
    the tile would be a to-do list they have no way to work."""
    client = _otp_client(_group_user("ana", "data_analyst"))
    index = client.get(reverse("admin:index"))
    assert "awaiting_repeat" not in [t.key for t in index.context["dashboard_tiles"]]
    assert client.get(reverse("admin:serology_repeat_worklist")).status_code == 403


def test_the_tile_count_matches_the_worklist_total(db):
    visit = _visit(_recipient())
    _serology(visit)
    _serology(_visit(_recipient("SCMVR32")))
    _donor_serology()

    client = _otp_client(_group_user("dm", "data_manager"))
    index = client.get(reverse("admin:index"))
    tile = next(t for t in index.context["dashboard_tiles"] if t.key == "awaiting_repeat")
    worklist = client.get(reverse("admin:serology_repeat_worklist"))
    assert tile.count == worklist.context["total"] == 2


def test_the_worklist_deep_links_the_repeat_with_the_pointer_prefilled(db):
    """Linking the pair by construction rather than by the operator remembering
    to link it - an unlinked repeat reads as two unrelated draws at one
    timepoint, which is the thing this ticket exists to prevent."""
    visit = _visit(_recipient())
    pending = _serology(visit)

    client = _otp_client(_group_user("dm", "data_manager"))
    row = client.get(reverse("admin:serology_repeat_worklist")).context["rows"][0]
    assert f"repeats={pending.pk}" in row["repeat_url"]
    assert f"recipient_visit={visit.pk}" in row["repeat_url"]


# --- the export contract ---------------------------------------------------

def test_the_export_carries_the_repeat_pairing(db, tmp_path):
    """R excludes grayzone draws from the analysis against this file, so it has to
    be able to see which draw resolved which. An id pointing at the `id` column
    already in the file carries no calendar or subject fact of its own."""
    import csv

    from django.core.management import call_command

    visit = _visit(_recipient())
    first = _serology(visit)
    second = _serology(visit, igg=REACTIVE_IGG, repeats=first)

    call_command("export_analysis_set", "v0.1", outdir=str(tmp_path))
    rows = {
        int(r["id"]): r
        for r in csv.DictReader((tmp_path / "v0.1" / "cmvserology.csv").open())
    }

    assert rows[first.pk]["repeats"] == ""
    assert rows[first.pk]["igg_interpretation"] == "equivocal"
    assert rows[second.pk]["repeats"] == str(first.pk)
