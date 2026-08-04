"""The stored reagent generation has to be a code the band maps recognize.

`reagent_generation` is not an ordinary descriptive column. It KEYS the band maps
that `interpret_igg` and `interpret_igm` read, so an unrecognized value does not
degrade one field: every interpretation on the row stops answering, and with it
the serology changelist, `Recipient.pre_kt_igg_serostatus`, `Donor.baseline_serostatus`
and `export_analysis_set`, which aborts rather than writing a partial snapshot.

`choices` guards only the admin form. The shell and ingest paths that a data fix
actually arrives through never see it, which is where a mis-cased or legacy code
comes from. So the rule gets the model's usual dual guard: `clean()` for a
readable admin error, a `CheckConstraint` for the bare-save path.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from subay.registry.models import CMVSerology, Recipient, RecipientVisit
from subay.registry.serology_ranges import (
    GEN1,
    GEN2,
    VALID_GENERATIONS,
    interpret_igg,
    interpret_igm,
)

DRAWN = date(2026, 6, 3)


@pytest.fixture
def visit(db):
    r = Recipient.objects.create(
        subject_id="SCMVR01", date_of_birth=date(1980, 1, 1), sex="M", kt_date=DRAWN
    )
    return RecipientVisit.objects.create(
        recipient=r, timepoint_label="pre_kt", actual_visit_date=DRAWN
    )


def _unsaved(visit, generation):
    return CMVSerology(
        recipient_visit=visit,
        value=Decimal("1.50"),
        drawn_date=DRAWN,
        reagent_generation=generation,
    )


# ------------------------------------------------------------------ clean()


@pytest.mark.parametrize("bad", ["GEN2", "gen 2", "gen3", "2", "second"])
def test_clean_rejects_a_generation_the_band_maps_cannot_key(visit, bad):
    with pytest.raises(ValidationError) as exc:
        _unsaved(visit, bad).full_clean()
    assert "reagent_generation" in exc.value.message_dict


def test_the_clean_error_names_the_codes_that_would_work(visit):
    """A data manager correcting a late-entered sample should not have to read
    the source to find out what to type."""
    with pytest.raises(ValidationError) as exc:
        _unsaved(visit, "GEN2").full_clean()
    message = " ".join(exc.value.message_dict["reagent_generation"])
    for code in VALID_GENERATIONS:
        assert code in message


@pytest.mark.parametrize("good", sorted(VALID_GENERATIONS))
def test_clean_accepts_every_generation_the_band_maps_know(visit, good):
    _unsaved(visit, good).full_clean()  # must not raise


def test_clean_still_accepts_blank(visit):
    """Blank is the documented "default from the draw date" input, not a bad
    value. save() fills it and effective_reagent_generation resolves it, so the
    guard must not turn the ordinary entry path into an error."""
    _unsaved(visit, "").full_clean()  # must not raise


# ------------------------------------------------------- the bare-save path


def test_the_database_refuses_a_bad_generation_on_the_bare_save_path(visit):
    """The defect, reproduced. `CMVSerology.objects.create(...)` never calls
    full_clean(), so before this constraint a mis-cased code persisted happily
    and every interpretation on the row raised KeyError afterwards."""
    with pytest.raises(IntegrityError), transaction.atomic():
        CMVSerology.objects.create(
            recipient_visit=visit,
            value=Decimal("1.50"),
            drawn_date=DRAWN,
            reagent_generation="GEN2",
        )
    assert not CMVSerology.objects.filter(reagent_generation="GEN2").exists()


def test_the_database_refuses_a_bad_generation_on_a_later_update(visit):
    """queryset.update() bypasses save() and clean() alike, which is the shape a
    bulk data fix takes."""
    s = CMVSerology.objects.create(
        recipient_visit=visit, value=Decimal("1.50"), drawn_date=DRAWN
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        CMVSerology.objects.filter(pk=s.pk).update(reagent_generation="gen3")
    s.refresh_from_db()
    assert s.reagent_generation == GEN2


def test_a_row_written_bare_still_interprets(visit):
    """The constraint has to leave the normal bare-save path working. save()
    fills the generation from the draw date, and the interpretation follows."""
    s = CMVSerology.objects.create(
        recipient_visit=visit, value=Decimal("1.50"), drawn_date=DRAWN
    )
    assert s.reagent_generation == GEN2
    assert s.igg_interpretation == "reactive"  # 1.50 >= 1.20 on 2nd generation


# ------------------------------------------------------ the in-memory case


@pytest.mark.parametrize("interpret", [interpret_igg, interpret_igm])
def test_an_unknown_generation_fails_by_name_not_as_a_keyerror(interpret):
    """Defense in depth, and the part a reviewer reads. The constraint makes this
    unreachable from a persisted row, but an object built in memory can still
    carry a typo, and `KeyError: 'GEN2'` from inside a private map says nothing
    about which field is wrong."""
    with pytest.raises(ValueError, match="Unknown reagent generation 'GEN2'"):
        interpret(Decimal("1.50"), "GEN2")


@pytest.mark.parametrize("generation", [GEN1, GEN2])
def test_the_guard_does_not_disturb_a_known_generation(generation):
    assert interpret_igg(Decimal("1.50"), generation) is not None
    assert interpret_igm(Decimal("1.50"), generation) is not None
