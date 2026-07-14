# Task — SUBAY Slice 14: Safety release-timeliness surface

## Context (carry forward)
- Stack: Django + `subay` package, app `subay/registry/`. Validation lives on
  the models. Test harness: `conda run -n subay_env python -m pytest -q`.
- Slices 00–13 are merged and green. This reuses the QNAT model (slice 05) plus a
  lightweight release-event record; it is an analytics view, not heavy schema.
- Source of truth: `prd/issues/14-safety-release-timeliness.md`. Parent spec:
  `prd/CMV-KT_Research_Database_PRD.md`. Read the card before planning.
- The export chokepoint is
  `subay/registry/management/commands/export_analysis_set.py`. Extend it.

## Goal (target state)
An active safety net so the O4 safety-release SOP has AUTOMATED detection rather
than manual vigilance. A Safety Monitor gets a standing flag the moment a
high-viral-load or symptomatic result goes un-actioned past the deadline.

## Scope
IN — only this slice:
- A standing query flagging any QNAT ≥ 10,000 IU/mL OR symptomatic flag with NO
  logged release-event within 24h → flag the Safety Monitor.
- A lightweight release-event record; a release logged within 24h CLEARS the
  flag. Threshold (10,000) and window (24h) are EXPLICIT named constants, not
  magic buried in a view.
- A missed/late release recordable as a PROTOCOL DEVIATION, and additionally as a
  research-related SAE IF it caused harm (dual-track).
- The flag and deviation/SAE records reproducible from stored data (no manual
  list).
- Safety records in the slice 01 export as day-offsets.

OUT — do NOT build now:
- Notification delivery/transport; only the standing flag + records here.

## Constraints
MUST:
- Keep all existing tests passing; ADD tests, never weaken them.
- Threshold and window are explicit named constants.
- The flag is reproducible from stored data (a query/view), not a manual list.
- Validation at the model layer; subject IDs stay STRINGS;
  `django-simple-history` on the new records.

MUST NOT:
- Hard-code the threshold/window as unfindable magic numbers in a view.
- Conflate the protocol-deviation and SAE tracks.
- Emit any calendar date, name, MRN, or address in any export file (de-id
  chokepoint intact; dates as day-offsets).
- Touch `.env`, secrets, settings DB credentials, `deploy/`, or CI config.
- Add a Python dependency without stating why in the plan first.

## Acceptance criteria (all must pass — binary)
- [ ] A standing query flags QNAT ≥ 10,000 IU/mL (or a symptomatic flag) with no release-event logged within 24h.
- [ ] A release-event logged within 24h clears the flag; the threshold and window are explicit, not hard-coded magic in a view nobody can find.
- [ ] A missed/late release is recordable as a protocol deviation, and as a research-related SAE when it caused harm (dual-track).
- [ ] The flag and the deviation/SAE records are reproducible from stored data (no manual list).
- [ ] Safety records appear in the de-identified export (slice 01) as day-offsets.

## Approach
Thin slice — an analytics view over existing models + a release-event record.
Build the standing-flag query test-first (≥10,000 un-actioned → flagged; release
within 24h → cleared) with the threshold/window as named constants. Wire the
deviation/SAE records and export after.

## Done when
Every acceptance-criteria box is satisfied, the full suite is green
(`conda run -n subay_env python -m pytest -q`, old + new), migrations are clean
(`conda run -n subay_env python manage.py makemigrations --check`), the
backpressure collector exits 0
(`conda run -n subay_env python scripts/backpressure.py`), and the Reviewer hat
approves. When the Reviewer approves, print LOOP_COMPLETE.
