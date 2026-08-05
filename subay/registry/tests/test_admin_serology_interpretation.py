"""Slice 17 ticket 03 - the admin shows what the result actually says.

A data manager entering a serology, and a clinician performing four-eyes
verification on it, both used to see a yes/no icon derived from the retired
2.0 AU/mL cutoff. Under the second-generation ranges that icon can be wrong in
two ways at once: it applies the old threshold, and it has no way to say
"equivocal". A sign-off against a rounded boolean does not attest to the
interpretation that was actually applied.

The reagent generation is shown alongside, so nobody has to know the
2026-06-03 advisory date by heart to read a row.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from subay.registry.admin import CMVSerologyAdmin, CMVSerologyInline
from subay.registry.models import CMVSerology, Recipient, RecipientVisit

GEN2_DRAW = date(2026, 7, 1)   # on/after the advisory
GEN1_DRAW = date(2026, 6, 2)   # the day before it


@pytest.fixture
def admin_client(db):
    user = User.objects.create_superuser("root", "root@x", "pw")
    device = TOTPDevice.objects.create(user=user, name="test", confirmed=True)
    client = Client()
    client.force_login(user)
    session = client.session
    session["otp_device_id"] = device.persistent_id
    session.save()
    return client


@pytest.fixture
def visit(db):
    r = Recipient.objects.create(
        subject_id="SCMVR01", date_of_birth=date(1980, 1, 1), sex="M",
        kt_date=date(2026, 6, 1),
    )
    return RecipientVisit.objects.create(
        recipient=r, timepoint_label="day_7", actual_visit_date=GEN2_DRAW
    )


def _serology(visit, value="1.00", igm=None, drawn=GEN2_DRAW):
    return CMVSerology.objects.create(
        recipient_visit=visit,
        value=Decimal(value),
        igm_value=None if igm is None else Decimal(igm),
        igm_status="missing" if igm is None else "reported",
        result_status="reported",
        drawn_date=drawn,
    )


# --- the surfaces are wired to the interpretation, not the boolean ----------


def test_every_serology_surface_shows_the_interpretation():
    """Five places named a positivity boolean. The inline is the easy one to
    miss: it declares its own readonly_fields hundreds of lines from the admin
    registration that looks like the only one."""
    assert "igg_interpretation" in CMVSerologyAdmin.list_display
    assert "igg_interpretation" in CMVSerologyAdmin.readonly_fields
    assert "igm_interpretation" in CMVSerologyAdmin.readonly_fields
    assert "igg_interpretation" in CMVSerologyInline.readonly_fields
    # The wrapper each surface renders through must exist on the class.
    assert callable(getattr(CMVSerologyAdmin, "igg_interpretation", None))
    assert callable(getattr(CMVSerologyAdmin, "igm_interpretation", None))
    assert callable(getattr(CMVSerologyInline, "igg_interpretation", None))


def test_the_admin_no_longer_surfaces_the_retired_booleans():
    """Nothing an operator looks at is derived from the 2.0 AU/mL cutoff.

    The name checks stay after ticket 07 deleted the properties. An admin
    surface is a list of STRINGS, so re-adding "is_positive" to one would not
    raise AttributeError the way a real caller now does: Django would fail at
    render, or on a bad day render an empty column. The string is the only thing
    that can be asserted here, and it is worth asserting for exactly that
    reason.
    """
    for surface in (CMVSerologyAdmin.list_display, CMVSerologyAdmin.readonly_fields):
        assert "is_positive" not in surface
        assert "igm_positive" not in surface
    assert "is_positive" not in CMVSerologyInline.readonly_fields


def test_the_reagent_generation_is_visible_to_a_verifier():
    """Without it a clinician cannot tell which ranges a row was read against,
    and would have to know the advisory date by heart.

    The column is rendered by a callable rather than the field itself, so this
    also pins that the callable still sorts by the stored value: a generation
    column a verifier cannot order by is half a column.
    """
    assert "reagent_generation_label" in CMVSerologyAdmin.list_display
    assert CMVSerologyAdmin.reagent_generation_label.admin_order_field == "reagent_generation"


def test_the_visit_inline_can_set_the_reagent_generation():
    """The visit page is where a serology row is normally entered, so it is where
    a late-arriving first-generation sample has to be correctable.

    It was excluded while the inline's container clipped its overflow: an added
    column went out of reach rather than merely making the table wide. The CSS
    now scrolls the inline, so the width objection no longer buys anything, and
    leaving it out means save() stamps gen2 with nothing on screen to say so.
    """
    assert "reagent_generation" not in CMVSerologyInline.exclude
    # `repeats` stays out for a reason width does not cover: it is a select over
    # every serology row in the register.
    assert "repeats" in CMVSerologyInline.exclude


@pytest.mark.django_db
def test_the_visit_page_renders_the_generation_field_in_the_inline(admin_client, visit):
    """Declared-and-excluded is invisible in the same way as never-declared, so
    this asserts the rendered page rather than the ModelAdmin attribute."""
    _serology(visit, value="1.50")
    html = admin_client.get(
        reverse("admin:registry_recipientvisit_change", args=[visit.pk])
    ).content.decode()

    assert "serologies-0-reagent_generation" in html
    # And the option an operator would pick for a late first-generation sample.
    assert "1st generation (before 2026-06-03)" in html


# --- what actually renders -------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "value,expected",
    [
        ("0.50", "Non-reactive"),
        ("1.00", "Equivocal"),   # 0.80 to <1.20 on second-generation reagent
        ("1.50", "Reactive"),
    ],
)
def test_change_form_states_the_igg_interpretation_in_words(
    admin_client, visit, value, expected
):
    s = _serology(visit, value=value)
    html = admin_client.get(
        reverse("admin:registry_cmvserology_change", args=[s.pk])
    ).content.decode()
    assert expected in html
    # Three states cannot ride a two-state icon, so no icon should appear for it.
    assert 'class="readonly">None<' not in html
    assert 'class="readonly">True<' not in html
    assert 'class="readonly">False<' not in html


@pytest.mark.django_db
def test_an_unmeasured_channel_renders_a_placeholder_not_none(admin_client, visit):
    """igm_status defaults to 'missing', so igm_interpretation is None. None
    means no observation was obtained, not a fourth clinical answer, and it must
    not reach the page as the literal string."""
    s = _serology(visit, value="1.50", igm=None)
    assert s.igm_interpretation is None
    html = admin_client.get(
        reverse("admin:registry_cmvserology_change", args=[s.pk])
    ).content.decode()
    assert 'class="readonly">None<' not in html
    assert 'class="readonly">-</div>' in html


@pytest.mark.django_db
def test_an_unsaved_row_with_no_draw_date_does_not_crash(admin_client, visit):
    """Regression: surfacing the interpretation in the admin crashed the visit
    change page with a 500.

    The admin renders UNSAVED instances - the add form, and the serology inline's
    empty row - where drawn_date is still None. save() is what fills the reagent
    generation, so on those rows there is nothing to read the value against and
    generation_for() was comparing None to a date. Every ticket-01 test created a
    saved row, so no model test reached this path; it took putting the value on
    a page to find it.
    """
    blank = CMVSerology()
    assert blank.effective_reagent_generation is None
    assert blank.igg_interpretation is None
    assert blank.igm_interpretation is None

    # The page that actually broke.
    resp = admin_client.get(reverse("admin:registry_recipientvisit_change", args=[visit.pk]))
    assert resp.status_code == 200
    assert admin_client.get(reverse("admin:registry_cmvserology_add")).status_code == 200


def test_wide_inlines_can_scroll_rather_than_clipping():
    """The IgG interpretation column lands past the fold of the serology inline.

    `.module` sets overflow:hidden so children clip to the rounded corner, which
    turned that overflow into deletion: no scrollbar, and the rightmost columns
    simply gone. Measured on the visit change page at 1440px, five were
    unreachable, including drawn date and IgM value, which an operator has to
    type into. This card's own column was among them, so shipping without the
    scroll rule would have met the acceptance criterion in code while the data
    manager still could not see the reading.

    Asserted against the stylesheet because the clipping is pure CSS: no Django
    test client can see it, and the browser check that found it is not part of
    this suite.
    """
    from pathlib import Path

    css = Path(__file__).resolve().parents[3] / "static/admin/css/subay.css"
    rule = [
        line for line in css.read_text().splitlines()
        if "overflow-x" in line and "auto" in line
    ]
    assert rule, "no overflow-x:auto rule left in subay.css"
    assert any("fieldset.module" in line for line in css.read_text().splitlines()), (
        "the inline scroll rule was removed; wide inlines clip their rightmost "
        "columns with no scrollbar"
    )


def _css_rules():
    """(selector, body) for every declaration block in subay.css, comments stripped."""
    import re
    from pathlib import Path

    css = (Path(__file__).resolve().parents[3] / "static/admin/css/subay.css").read_text()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [
        (m.group(1).strip(), m.group(2))
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
    ]


def test_the_inline_scroller_is_not_a_fieldset():
    """The scroll must sit on the wrapping DIV, never on the fieldset itself.

    The first fix put `overflow-x:auto` on `fieldset.module` and looked right
    from script: `scrollLeft` moved, and a wheel gesture over the inline moved
    it too. It was still broken. Blink lays a fieldset's children out in an
    anonymous content box that `overflow` on the fieldset never reaches, so the
    element clips its 858px of extra columns and paints NO scrollbar. Measured
    headed at 1440px on the visit change page: fieldset reserved 0px of gutter
    while a plain DIV injected beside it reserved the normal 15px. Nothing on
    screen told the operator the columns existed.

    So the rule under test is not "some overflow-x:auto exists" - the broken
    version satisfied that. It is that no fieldset is the scroller, and that the
    fieldset is put back to overflow:visible, since a visible axis paired with a
    clipped one silently computes back to auto.
    """
    offenders, wrapper_scrolls, fieldset_reset = [], False, False
    for selector, body in _css_rules():
        decls = body.replace(" ", "")
        scrolls = "overflow-x:auto" in decls or "overflow:auto" in decls
        if scrolls and "fieldset" in selector:
            offenders.append(selector)
        if scrolls and ".inline-related" in selector and "fieldset" not in selector:
            wrapper_scrolls = True
        if "fieldset.module" in selector and "overflow:visible" in decls:
            fieldset_reset = True

    assert not offenders, (
        "a fieldset is the inline scroller, which clips with no visible "
        "scrollbar in Blink: " + ", ".join(offenders)
    )
    assert wrapper_scrolls, (
        "no non-fieldset .inline-related rule scrolls the wide inline; its "
        "rightmost columns are unreachable"
    )
    assert fieldset_reset, (
        "fieldset.module must be reset to overflow:visible, or it keeps "
        "clipping inside the scrolling wrapper"
    )


@pytest.mark.django_db
def test_the_changelist_reads_each_row_against_its_own_generation(admin_client, visit):
    """The defect made visible where a data manager actually works. The same
    1.50 AU/mL is non-reactive on first-generation reagent and reactive on
    second, and the changelist must not flatten that to one answer."""
    _serology(visit, value="1.50", drawn=GEN1_DRAW)
    _serology(visit, value="1.50", drawn=GEN2_DRAW)
    html = admin_client.get(reverse("admin:registry_cmvserology_changelist")).content.decode()
    assert "Non-reactive" in html
    assert "Reactive" in html
    # And the generation that explains the difference is on the row.
    assert "1st generation" in html
    assert "2nd generation" in html


@pytest.mark.django_db
def test_the_changelist_cell_drops_the_advisory_date_from_the_label(admin_client, visit):
    """The row says which generation; the form says which dates.

    The full choice label is what a data manager picks from when correcting a
    late first-generation sample, so the change form keeps it. In an 98px
    changelist column it wrapped to three lines and set every row to 87px, so
    the cell shows the ordinal alone.

    Asserted on the CELL, not on the page: the filter rail renders the same
    choices with their dates intact, so a bare `not in html` would fail for a
    reason that has nothing to do with the row.
    """
    _serology(visit, value="1.50", drawn=GEN1_DRAW)
    html = admin_client.get(reverse("admin:registry_cmvserology_changelist")).content.decode()
    assert '<td class="field-reagent_generation_label">1st generation</td>' in html
    # The dates are still reachable, one click away on the change form.
    assert "1st generation (before 2026-06-03)" in admin_client.get(
        reverse("admin:registry_cmvserology_add")
    ).content.decode()
