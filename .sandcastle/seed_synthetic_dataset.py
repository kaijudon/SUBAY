#!/usr/bin/env python
"""Bulk-seed a synthetic ~40-subject study dataset for the AFK data-entry tester
(ticket T3 / #14).

Run inside the disposable sandbox against the throwaway DB the hat already points
Django at (DATABASE_URL -> a scratch SQLite file). It bulk-creates the study's
Recipient / Donor / Visit / Serology shape directly through the ORM - NEVER by
typing through the admin UI - so the Playwright pass spends its time INSPECTING
forms, not populating them.

Everything is synthetic fixture data generated FRESH each run (the RNG is seeded
from the wall clock, and the hat drops + re-migrates the DB every iteration), so
no value ever resembles real SPMC PHI (RA 10173, DEC-025). Subject IDs stay
strings in the [S|D]CMV[R|D][NN] shape.

Side effects:
  * creates ~32 Recipients (+6 visits +serology each) and ~8 Donors (+draw
    +baseline serology) in the DB the environment's DATABASE_URL points at;
  * writes a form MANIFEST to $AFK_MANIFEST (default /tmp/afk_manifest.json): the
    pool of admin add- and change-form URLs pick_rotation_subset.py rotates over.

Rows are constructed valid-by-construction and saved with plain .save() (which
skips clean()); the seed therefore only ever emits rows that satisfy the model
rules (visits within the +3-day cap, is_verified=False so the four-eyes gate
stays dormant). It is not a fuzzer - probing invalid input is the browser pass's
job, done against the real admin forms.

    python .sandcastle/seed_synthetic_dataset.py
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from datetime import date, timedelta

import django

# Run as a standalone script: sys.path[0] is this file's dir (.sandcastle/), so
# the repo root (its parent) must be added for `import subay...` to resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "subay.settings")
django.setup()

from subay.registry.models import (  # noqa: E402  (after django.setup)
    CMVSerology,
    Donor,
    DonorVisit,
    Recipient,
    RecipientVisit,
)
from subay.registry.scheduling import TIMEPOINT_OFFSETS  # noqa: E402

# Fresh randomness every iteration so the synthetic dataset differs run to run.
RNG = random.Random(int(time.time() * 1000) ^ os.getpid())

N_RECIPIENTS = 32
N_DONORS = 8
TIMEPOINTS = list(TIMEPOINT_OFFSETS)  # pre_kt, day_7, ... day_180 (in order)
MANIFEST_PATH = os.environ.get("AFK_MANIFEST", "/tmp/afk_manifest.json")

# Admin add-forms worth inspecting even with no row selected - the empty add view
# is where required-field markers and widget rendering are checked. Keyed by the
# model's admin url name (app_label is always "registry").
ADD_FORM_MODELS = [
    "recipient",
    "donor",
    "recipientvisit",
    "donorvisit",
    "cmvserology",
    "cmvquantitative",
    "renalfunction",
    "druglevel",
    "tbnkpanel",
    "rejectionepisode",
]


def _admin_url(model_name: str, kind: str, pk: str | None = None) -> str:
    base = f"/admin/registry/{model_name}/"
    return f"{base}add/" if kind == "add" else f"{base}{pk}/change/"


def _rand_dob() -> date:
    # Adults 25-70y at an arbitrary synthetic reference; never a real birthdate.
    return date(RNG.randint(1955, 2000), RNG.randint(1, 12), RNG.randint(1, 28))


def _serostatus():
    return RNG.choice(["POS", "NEG", None])


def _tri_state():
    return RNG.choice([True, False, None])


def seed() -> dict:
    manifest: list[dict] = []

    # --- Donors first (recipients may FK a donor) --------------------------------
    donors: list[Donor] = []
    for i in range(1, N_DONORS + 1):
        d = Donor(
            subject_id=f"DCMVD{i:02d}",
            date_of_birth=_rand_dob(),
            sex=RNG.choice(["M", "F"]),
            donor_type=RNG.choice(["living", "deceased", None]),
            relation=RNG.choice(["sibling", "parent", "spouse", "", ""]),
        )
        d.save()
        donors.append(d)

        dv = DonorVisit(donor=d, draw_date=_rand_dob().replace(year=2024))
        dv.save()

        # A donor carries at most one baseline serology (unique per donor).
        val = None if RNG.random() < 0.1 else round(RNG.uniform(0.1, 60.0), 2)
        CMVSerology(
            donor=d,
            value=val,
            result_status="reported" if val is not None else "missing",
            igm_status="missing",
            drawn_date=dv.draw_date,
        ).save()

        manifest.append(
            {"model": "donor", "kind": "change", "pk": d.subject_id,
             "url": _admin_url("donor", "change", d.subject_id),
             "label": f"Donor {d.subject_id}"}
        )

    # --- Recipients + their 6-timepoint timeline ---------------------------------
    for i in range(1, N_RECIPIENTS + 1):
        kt = date(2024, 1, 1) + timedelta(days=RNG.randint(0, 300))
        r = Recipient(
            subject_id=f"SCMVR{i:02d}",
            date_of_birth=_rand_dob(),
            sex=RNG.choice(["M", "F"]),
            kt_date=kt,
            donor_serostatus=_serostatus(),
            recipient_serostatus=_serostatus(),
            donor=RNG.choice(donors) if RNG.random() < 0.6 else None,
            has_diabetes=_tri_state(),
            has_hypertension=_tri_state(),
            dialysis_vintage_months=RNG.choice([None, 6, 12, 24, 48]),
            induction_agent=RNG.choice(["atg", "basiliximab", "none", None]),
            completion_status=RNG.choice(
                ["enrolled", "completed", "completed", "withdrawn",
                 "lost_to_followup", "graft_loss", "died"]
            ),
        )
        r.save()
        manifest.append(
            {"model": "recipient", "kind": "change", "pk": r.subject_id,
             "url": _admin_url("recipient", "change", r.subject_id),
             "label": f"Recipient {r.subject_id}"}
        )

        # Enter a prefix of the protocol timepoints (some recipients partial),
        # so the change-form pool spans early and late visits.
        n_visits = RNG.randint(1, len(TIMEPOINTS))
        for label in TIMEPOINTS[:n_visits]:
            nominal = kt + timedelta(days=TIMEPOINT_OFFSETS[label])
            # Mostly on-window (within the +3-day cap); occasionally a genuine
            # missed_visit past the cap, kept valid by setting the status.
            if RNG.random() < 0.12:
                actual = nominal + timedelta(days=RNG.randint(4, 20))
                status = "missed_visit"
            else:
                actual = nominal + timedelta(days=RNG.randint(0, 3))
                status = "completed"
            v = RecipientVisit(
                recipient=r, timepoint_label=label,
                actual_visit_date=actual, completion_status=status,
            )
            v.save()

            # Serology on the pre_kt visit (drives pre_kt_igg_serostatus) and a
            # sampling of later visits, to populate the CMVSerology change pool.
            if label == "pre_kt" or RNG.random() < 0.3:
                val = None if RNG.random() < 0.1 else round(RNG.uniform(0.1, 80.0), 2)
                igm_val = round(RNG.uniform(0.1, 40.0), 2) if RNG.random() < 0.2 else None
                s = CMVSerology(
                    recipient_visit=v,
                    value=val,
                    result_status="reported" if val is not None else "missing",
                    igm_value=igm_val,
                    igm_status="reported" if igm_val is not None else "missing",
                    drawn_date=actual,
                )
                s.save()
                manifest.append(
                    {"model": "cmvserology", "kind": "change", "pk": str(s.pk),
                     "url": _admin_url("cmvserology", "change", str(s.pk)),
                     "label": f"CMVSerology #{s.pk} ({r.subject_id}/{label})"}
                )

            manifest.append(
                {"model": "recipientvisit", "kind": "change", "pk": str(v.pk),
                 "url": _admin_url("recipientvisit", "change", str(v.pk)),
                 "label": f"Visit {r.subject_id}/{label}"}
            )

    # Empty add-forms: required-marker + widget rendering is checked here.
    for m in ADD_FORM_MODELS:
        manifest.append(
            {"model": m, "kind": "add", "pk": None,
             "url": _admin_url(m, "add"),
             "label": f"Add {m}"}
        )

    RNG.shuffle(manifest)  # so a truncated pool still spans model kinds
    return {
        "counts": {
            "recipients": Recipient.objects.count(),
            "donors": Donor.objects.count(),
            "recipient_visits": RecipientVisit.objects.count(),
            "serologies": CMVSerology.objects.count(),
            "form_targets": len(manifest),
        },
        "forms": manifest,
    }


if __name__ == "__main__":
    result = seed()
    with open(MANIFEST_PATH, "w") as fh:
        json.dump(result, fh, indent=2)
    c = result["counts"]
    print(
        f"SEEDED {c['recipients']} recipients, {c['donors']} donors, "
        f"{c['recipient_visits']} visits, {c['serologies']} serologies -> "
        f"{c['form_targets']} form targets in {MANIFEST_PATH}"
    )
