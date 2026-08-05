"""The pre-authentication surface: the landing page and the protocol summary.

These are the only two views in SUBAY that serve an unauthenticated request, so
they carry one extra rule on top of the usual ones:

    **Nothing rendered here may be traceable to a subject.** No subject ID, no
    date drawn from a subject's record, no per-recipient row - only study-level
    aggregates. The de-identification chokepoint guards the export; this module
    guards the front door.

    "Date drawn from a subject's record" is the whole of the rule. The assay
    advisory date below is a published fact about the laboratory's reagent, in
    the same class as the QNAT limit of detection, and it says nothing about any
    subject - which is why the leak test checks kt_date and date_of_birth
    renderings rather than banning every date-shaped string.

Everything factual on both pages is read from the registry's own constants and
querysets rather than retyped as prose (`TIMEPOINT_OFFSETS`, `VISIT_SHIFT_CAP_DAYS`,
`CMVQuantitative.LOD`, `serology_ranges.bands_for`, `safety.RELEASE_*`). A
threshold quoted on a public page that disagrees with the threshold the software
enforces is worse than no page at all, and deriving it is the only way the two
cannot drift.
"""
import datetime

from django.shortcuts import render
from django.urls import reverse

from . import safety
from .models import (
    CMVQuantitative,
    Recipient,
    RecipientVisit,
    VISIT_SHIFT_CAP_DAYS,
)
from .scheduling import TIMEPOINT_OFFSETS
from .serology_ranges import ADVISORY_EFFECTIVE, GEN2, bands_for, generation_for

# The protocol's enrolment target and follow-up horizon. Not derivable from any
# stored row - the target is a fact about the study, not about the data - so it
# lives here as a named constant rather than as a number inline in a template.
TARGET_RECIPIENTS = 40
FOLLOWUP_DAYS = max(TIMEPOINT_OFFSETS.values())

# What each timepoint is drawn for. Keyed by the SAME labels as TIMEPOINT_OFFSETS
# so a new timepoint added to the spine shows up here as a missing key rather
# than silently rendering an empty row.
TIMEPOINT_COLLECTIONS = {
    "pre_kt": "Baseline serology for donor and recipient, QNAT, renal function, TBNK panel",
    "day_7": "QNAT, drug level, renal function",
    "day_30": "QNAT, serology, drug level, renal function, TBNK panel",
    "day_90": "QNAT, serology, drug level, renal function",
    "day_120": "QNAT, drug level, renal function",
    "day_180": "QNAT, serology, drug level, renal function, TBNK panel, outcome assessment",
}

# Presentation for the three derived risk strata plus the undetermined case.
# `key` doubles as the pill modifier class, so a stratum's colour is decided once.
STRATUM_PRESENTATION = [
    (
        "high",
        "D+/R−",
        "High risk",
        "The primary-infection group. Three months of prophylaxis and the tightest "
        "QNAT schedule - no result in this stratum may go unverified.",
    ),
    (
        "intermediate",
        "R+",
        "Intermediate risk",
        "Reactivation rather than primary infection. Prophylaxis by clinician "
        "judgement; the source label is recorded at each detectable draw.",
    ),
    (
        "low",
        "D−/R−",
        "Low risk",
        "Neither party seropositive. Followed on the same spine so the denominator "
        "stays whole, but no prophylaxis is expected.",
    ),
    (
        "none",
        "-",
        "Undetermined",
        "A serostatus was never recorded at transplant. The stratum stays blank "
        "rather than being guessed, and these recipients are reported separately.",
    ),
]

FEATURES = [
    {
        "icon": "ico-calendar",
        "title": "The visit spine, computed",
        "body": "Six timepoints per recipient, shifted forward past any day the clinic "
        "or lab is closed. The registry tells you what is due, overdue or missed "
        "- you never keep that list yourself.",
    },
    {
        "icon": "ico-shield",
        "title": "Four eyes on what matters",
        "body": "Serologies, drug levels, rejection episodes and genotype calls need a "
        "verifier who is not the person who typed them. Enforced in the model, "
        "not by convention.",
    },
    {
        "icon": "ico-alarm",
        "title": "Safety releases on a clock",
        "body": "A viral load at or above the release threshold, or any symptomatic "
        "draw, needs a logged release inside the SOP window. Anything late "
        "surfaces on its own, every day.",
    },
    {
        "icon": "ico-database",
        "title": "An append-only biobank",
        "body": "Remaining volume and thaw count are derived from a ledger of thaw and "
        "consumption events. A mistake is corrected by a new event, never by "
        "editing what the freezer did.",
    },
    {
        "icon": "ico-code",
        "title": "Genotyping with provenance",
        "body": "Sanger and qPCR results carry their pipeline run, reference set and "
        "content hash, so a call can always be traced back to the tube it came "
        "from.",
    },
    {
        "icon": "ico-team",
        "title": "Derive, don't store",
        "body": "Age, eGFR, risk stratum, CD4/CD8, episodes - all computed at read. A "
        "stored fact and its derived value can never quietly disagree.",
    },
]

RULES = [
    {
        "title": "Four eyes on every outcome-critical row",
        "body": "Serology, drug levels, rejection episodes and genotype calls need a "
        "verifier who is not the person who entered them. The registry will not "
        "let you sign off your own work.",
    },
    {
        "title": "Derived values are never stored",
        "body": "Age, risk stratum, drift days, episode counts and remaining aliquot "
        "volume are computed at read. They cannot drift out of step with the "
        "values they come from.",
    },
    {
        "title": "The biobank ledger is append-only",
        "body": "Thaws, consumption and releases are events. A mistake is corrected by "
        "a new event that says so, not by editing history.",
    },
    {
        "title": "Identifiers never reach the analysis set",
        "body": "Names, MRNs, addresses and dates of birth have no column in the export "
        "schema. Dates leave as day-offsets, and the export aborts entirely on a "
        "name-shaped value.",
    },
]


def _signin_url():
    """The admin login URL. Resolved by name so it follows whichever admin site
    instance is mounted rather than hard-coding /admin/login/."""
    return reverse("admin:login")


def _visit_spine():
    """The six protocol timepoints as display rows, in day order.

    The window column quotes VISIT_SHIFT_CAP_DAYS because that - not a per-
    timepoint tolerance - is the rule the model actually enforces: a draw more
    than +N days past nominal is forced to `missed_visit`.
    """
    return [
        {
            "timepoint": label,
            "offset": offset,
            "window": f"+{VISIT_SHIFT_CAP_DAYS} d cap",
            "collected": TIMEPOINT_COLLECTIONS[label],
        }
        for label, offset in sorted(TIMEPOINT_OFFSETS.items(), key=lambda kv: kv[1])
    ]


def _stratum_counts():
    """Recipients per derived risk stratum.

    `risk_stratum` is a @property over two nullable serostatus columns, not a
    database column, so this counts in Python rather than pretending a GROUP BY
    exists. n is bounded by the study's enrolment target, so the walk is cheap.
    """
    tally = {key: 0 for key, _code, _name, _body in STRATUM_PRESENTATION}
    for recipient in Recipient.objects.only(
        "donor_serostatus", "recipient_serostatus"
    ):
        tally[recipient.risk_stratum or "none"] += 1
    return [
        {"key": key, "code": code, "name": name, "body": body, "n": tally[key]}
        for key, code, name, body in STRATUM_PRESENTATION
    ]


def _long_date(day):
    """"3 June 2026". Long form because this renders inside a sentence, and
    spelled out here rather than via strftime("%-d") which is glibc-only."""
    return f"{day.day} {day.strftime('%B')} {day.year}"


def _grayzone_phrase(channel, equivocal_from, reactive_from):
    """One channel's grayzone as prose, or an honest statement that it has none.

    serology_ranges expresses a single-cutoff generation as a band whose two
    edges COINCIDE, so that one comparison serves both generations with no
    separate legacy path. That representation must not reach a reader as prose:
    interpolating it yields "2.00 to under 2.00", which states that a grayzone
    exists and is empty. No laboratory said that. The page has to translate the
    encoding rather than fill it into a sentence written for one generation.
    """
    if equivocal_from >= reactive_from:
        return f"{channel} is a single cutoff with no grayzone"
    return f"{channel} has a grayzone of {equivocal_from} to under {reactive_from}"


def _in_force_sentence(generation):
    """Which reagent the published numbers belong to, and from when.

    Without it the page states cutoffs with no period attached, so a reader
    holding a result drawn under the earlier reagent has no way to tell that
    these values were never applied to it. DEC-030 freezes those rows at their
    original reading, and that freeze is only legible if the boundary is named.
    """
    when = _long_date(ADVISORY_EFFECTIVE)
    if generation == GEN2:
        return (
            f" These are the second-generation reagent ranges, in force since {when}. "
            "A sample drawn before that date was read against the single "
            "first-generation cutoff that applied then, and is never re-interpreted "
            "against these values."
        )
    return (
        f" These are the first-generation reagent ranges, in force until the "
        f"laboratory's second-generation reagent takes effect on {when}."
    )


def _assays():
    """Assay cutoffs, each read from the constant that enforces it."""
    generation = generation_for(datetime.date.today())
    bands = bands_for(generation)
    igg_equivocal, igg_reactive = bands["igg"]
    igm_equivocal, igm_reactive = bands["igm"]
    grayzones = (
        f"{_grayzone_phrase('IgG', igg_equivocal, igg_reactive)}, and "
        f"{_grayzone_phrase('IgM', igm_equivocal, igm_reactive)}"
    )
    # The equivocal rule is stated only when there is a band for a result to land
    # in. Under a single-cutoff generation it would describe a state no result
    # can reach.
    equivocal_rule = (
        " A result inside one is recorded as equivocal, never rounded into a "
        "serostatus the laboratory did not give."
        if igg_equivocal < igg_reactive or igm_equivocal < igm_reactive
        else ""
    )
    return [
        {
            "name": "CMV quantitative (QNAT)",
            "cutoff": f"floor {CMVQuantitative.LOD} IU/mL",
            "body": f"{CMVQuantitative.ASSAY}. The limit of detection and the limit of "
            "quantification are the same number, so a result under the floor is "
            "stored as the floor with a below-floor flag, never as zero - the "
            "series stays honest about what the assay could see.",
        },
        {
            # The generation comes from today's date, not a hardcoded GEN2. The
            # page publishes the ranges IN FORCE, and the only way it stays that
            # way across the next advisory is to ask the same function the
            # interpreter asks. Rows drawn under the earlier reagent are still
            # read against the earlier bands (DEC-030), but a public summary of
            # what the lab runs today is not the place to publish both.
            "name": "CMV serology",
            "cutoff": f"IgG ≥ {igg_reactive} · IgM ≥ {igm_reactive} AU/mL",
            "body": "IgG and IgM channels, reactive at or above those values. "
            f"{grayzones}.{equivocal_rule}{_in_force_sentence(generation)} The "
            "donor's baseline draw derives the pair's serostatus, which is "
            "cross-checked against the status recorded at transplant and flagged "
            "- never overwritten - when the two disagree.",
        },
        {
            "name": "Release timeliness",
            "cutoff": f"≥ {safety.RELEASE_THRESHOLD_IU_ML:,.0f} IU/mL within "
            f"{int(safety.RELEASE_WINDOW.total_seconds() // 3600)} h",
            "body": "A QNAT at or above the threshold, or any symptomatic draw, needs a "
            "logged release-event inside the window. Timeliness is evaluated at "
            "day granularity because every date in the registry is a date, not a "
            "timestamp. A missed window is a protocol deviation.",
        },
        {
            "name": "Genotyping",
            "cutoff": "pinned reference set",
            "body": "Sanger or NGS with a run manifest. A resistance call is only "
            "readable against the reference-set version that produced it; sets "
            "are versioned, never edited.",
        },
    ]


def landing(request):
    """The public front door. Study-level counters only - see the module docstring."""
    return render(
        request,
        "public/landing.html",
        {
            "signin_url": _signin_url(),
            "target_recipients": TARGET_RECIPIENTS,
            "timepoint_count": len(TIMEPOINT_OFFSETS),
            "features": FEATURES,
            "stats": [
                {
                    "n": Recipient.objects.count(),
                    "label": f"recipients on the register · of {TARGET_RECIPIENTS} at target",
                },
                {
                    "n": RecipientVisit.objects.count(),
                    "label": "recipient visits captured on the spine",
                },
                {
                    "n": len(TIMEPOINT_OFFSETS),
                    "label": f"protocol timepoints over {FOLLOWUP_DAYS} days of follow-up",
                },
                {"n": 0, "label": "identifiers in the analysis set"},
            ],
        },
    )


def protocol(request):
    """The operational summary of the protocol, as the registry enforces it."""
    enrolled = Recipient.objects.count()
    return render(
        request,
        "public/protocol.html",
        {
            "signin_url": _signin_url(),
            "target_recipients": TARGET_RECIPIENTS,
            "followup_days": FOLLOWUP_DAYS,
            "timepoint_count": len(TIMEPOINT_OFFSETS),
            "visit_cap_days": VISIT_SHIFT_CAP_DAYS,
            "enrolled_recipients": enrolled,
            "spine": _visit_spine(),
            "strata": _stratum_counts(),
            "assays": _assays(),
            "rules": RULES,
            "stats": [
                {"n": TARGET_RECIPIENTS, "label": "adult kidney-transplant recipients at target"},
                {"n": enrolled, "label": "on the register to date"},
                {"n": len(TIMEPOINT_OFFSETS), "label": "protocol timepoints per recipient"},
                {"n": FOLLOWUP_DAYS, "label": "days of follow-up after transplant"},
            ],
        },
    )
