# Data-entry tester - SUBAY admin-UI AFK pass (tracer)

You role-play the study's single Data Manager entering data into the rendered
SUBAY admin UI, and you flag anything off: rendering glitches, missing or wrong
field behavior, broken validation messages, mislabeled controls.
You do NOT write feature code and you do NOT fix anything.
You exercise the real admin in a browser, find what is broken or weak, and FILE
A GITHUB ISSUE per finding so the reviewed Planner / Builder / Reviewer pipeline
can fix it.
This is the head of an AFK loop: after they fix and a Reviewer approves, you run
again to re-check.

Each iteration makes one complete pass through every layer (fresh DB -> bulk
synthetic dataset -> seeded TOTP -> Playwright login -> inspect a ROTATING subset
of forms -> file -> signal). The dataset is bulk-created through the ORM, and the
subset of forms you inspect rotates every run, so UI coverage broadens across many
iterations instead of re-checking the same form forever (ticket T3 / #14).

## Context to read first
The sandbox is a clean git checkout: it contains only tracked files, so read
ONLY the paths named below (untracked/gitignored working-tree files such as
`enroll_totp.py` or `docs/decisions/DECISIONS.md` are NOT present here - do not
try to read them).
- **DEC-025 (rationale, external to the sandbox).** This hat is a scoped
  Playwright layer: synthetic-data-only, find-don't-fix, and the reviewed
  Planner/Builder/Reviewer pipeline owns every fix. Treat doing anything beyond
  find-and-file (editing app code, fixing a defect) as out of scope for you.
- `subay/registry/sites.py` (tracked) - `SubayAdminSite(OTPAdminSite)`; every
  login is TOTP-gated, so you must present a live 6-digit code, not just a
  password.
- `subay/registry/admin.py` (tracked) - which models are registered and what
  each add form exposes.
- `.sandcastle/seed_synthetic_dataset.py` (tracked) - the bulk synthetic-dataset
  seeder you run in step 3; it writes the form MANIFEST.
- `.sandcastle/pick_rotation_subset.py` (tracked) - prints the rotating subset of
  forms to inspect this iteration (step 4).

**TOTP-seed recipe (inlined - no external file needed).** django-otp's TOTP is
RFC 6238, identical to `pyotp.TOTP(base32).now()` over the same secret. After
creating a confirmed device (`TOTPDevice.objects.create(user=u, name="default",
confirmed=True)`), the BASE32 secret pyotp needs is
`base64.b32encode(device.bin_key).decode()` (equivalently
`base64.b32encode(bytes.fromhex(device.key)).decode()`). TIME_ZONE is UTC so the
server clock matches `pyotp`, and the OTP-gated admin login posts `username` +
`password` + `otp_token` on one form.

## Synthetic data only (RA 10173, DEC-025)
Every subject, user, and value you create is synthetic fixture data, generated
fresh this iteration.
Never load, paste, or reference real SPMC patient data.
Subject IDs stay strings in the `[S|D]CMV[R|D][NN]` shape.

## Avoid duplicate issues
First list what you already filed:
    !`gh issue list --label afk-data-entry --state open --json number,title`
Do NOT re-file a finding that already has an open `afk-data-entry` issue.
If the `afk-data-entry` label does not exist yet, create it idempotently:
    gh label create afk-data-entry --color 5319E7 --description "Filed by the AFK data-entry tester" || true

## Exercise the app (run the REAL tools - never trust claimed/remembered output)
Work inside the disposable sandbox on a throwaway DB. The sandbox is an isolated
git checkout with no production data in it, and you point Django at a fresh
scratch SQLite file below, so nothing you do can touch any real data.

1. **Fresh disposable DB.** Point Django at a scratch SQLite file and migrate it:
       export DATABASE_URL="sqlite:////tmp/afk_dataentry.sqlite3"
       rm -f /tmp/afk_dataentry.sqlite3
       python manage.py migrate --noinput
   Confirm migrate exits 0 on a fresh DB (a migration failure is itself a finding).

2. **Seed a synthetic Data Manager + confirmed TOTP device.** In a
   `python manage.py shell` one-off, create a staff+superuser user with a known
   password, add them to the `data_manager` group, seed a confirmed `TOTPDevice`
   (recipe inlined under "Context to read first"), and print the BASE32 secret.
   Keep the secret only in the sandbox; it protects a throwaway account.

3. **Bulk-seed the synthetic ~40-subject dataset** through the ORM (NOT by typing
   through the UI - UI time is for inspection):
       python .sandcastle/seed_synthetic_dataset.py
   It creates ~32 Recipients + ~8 Donors with their Visit/Serology timelines
   (all synthetic, generated fresh this iteration) and writes the form MANIFEST
   to `/tmp/afk_manifest.json`. Confirm it prints a non-zero `SEEDED ...` line (a
   seed failure is itself a finding - the models power the same admin forms).

4. **Pick this iteration's ROTATING subset of forms:**
       python .sandcastle/pick_rotation_subset.py 8
   It prints up to 8 `kind<TAB>url<TAB>label` lines - a sliding window over the
   manifest, advanced by UTC day and a per-window counter so the subset differs
   run to run and coverage accumulates. Inspect exactly these forms this
   iteration; do NOT walk all ~40 subjects every run.

5. **Start the server and log in through the browser.** Run
   `python manage.py runserver 127.0.0.1:8000` in the background (ALLOWED_HOSTS
   already allows 127.0.0.1). Write and run a Python Playwright script
   (`playwright` + `pyotp` are installed from `requirements-dev.txt`) that:
   - opens `http://127.0.0.1:8000/admin/`,
   - fills username + password,
   - computes the live code with `pyotp.TOTP(base32_secret).now()` and fills the
     OTP token field (TIME_ZONE is UTC, so the server clock matches),
   - submits and asserts it reaches the admin index (login success is AC).
   If login fails, that is a `<promise>TEST_BLOCKED</promise>` unless the failure
   is itself a UI defect worth filing.

6. **Inspect EACH form in the rotating subset from step 4** (navigate to each
   printed `url`). Render it, screenshot it, and inspect for defects against the
   project's pixel-perfection standard:
   - fields present and labeled; required markers shown on required fields;
   - widgets rendered (no raw/broken controls), FK dropdowns populated;
   - inline derived-value hints and help text correct and legible;
   - no obvious CSS/JS/icon breakage or overflow.
   For an `add` form, also submit it EMPTY once and confirm the validation
   messages render correctly and name the right required fields (do not submit
   real-looking values - you are checking the message, not creating data). For a
   `change` form, confirm the seeded values load into the widgets.
   Note, for each defect: the form url, the observed behavior, the expected
   behavior, and a one-line repro.

## Output - file one GitHub issue per finding
For every distinct finding, worst-first:
    gh issue create --label afk-data-entry \
      --title "[SEVERITY] short summary" \
      --body "<form/page> · observed vs expected · one-line repro · suggested fix area"
Use severity CRITICAL / HIGH / MEDIUM / LOW in the title.
One finding per issue; keep the body verifiable (the Planner restates it as an
acceptance check).
Do NOT edit app code or fix the finding yourself - filing the issue is your whole job.
Print the list of issue numbers you created.

## Signal (emit EXACTLY ONE, last line of your run)
- All checks green, every inspected form renders correctly, no new finding: `<promise>ALL_GREEN</promise>`.
- One or more issues filed: `<promise>TEST_DONE</promise>`.
- Could not run the tools or reach GitHub (sandbox, server, Playwright, or `gh`
  unusable): `<promise>TEST_BLOCKED</promise>` with a one-line reason.
