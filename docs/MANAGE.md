# `manage.py` — Command Reference

`manage.py` is SUBAY's Django command-line entrypoint. It sets
`DJANGO_SETTINGS_MODULE=subay.settings` and hands off to Django's
`execute_from_command_line`, so it exposes **all built-in Django commands**
(`migrate`, `createsuperuser`, `runserver`, `shell`, `test`, …) plus the
three **custom commands** documented below.

## Running it

Load the environment first (the project env helper `subay-env` and the
`subay_env` conda env must be active), then:

```bash
cd /opt/subay
python manage.py <command> [args]
python manage.py help            # list every available command
python manage.py <command> --help  # flags for one command
```

---

## Custom commands

All three custom commands live in `subay/registry/management/commands/`.

### `enroll_totp` — bootstrap admin two-factor login

Creates (or resets) a **confirmed** `TOTPDevice` for a user so the admin
login page's OTP field works. The device is created already-confirmed, matching
the single-operator, trusted-box deploy model.

```bash
python manage.py enroll_totp <username>              # device 'operator'
python manage.py enroll_totp cmvprojectuser --device admin
python manage.py enroll_totp cmvprojectuser --qr     # scannable ASCII QR
python manage.py enroll_totp cmvprojectuser --token  # also print a valid token now
python manage.py enroll_totp cmvprojectuser --rotate # new secret for an existing device
```

| Argument   | Description |
|------------|-------------|
| `username` | Account to enroll (required). |
| `--device` | `TOTPDevice.name` (default: `operator`). |
| `--qr`     | Print a scannable ASCII QR of the enrollment `config_url`. |
| `--token`  | Also print the current valid TOTP token. |
| `--rotate` | Issue a fresh secret for an existing device (invalidates any authenticator already set up). |

Prints the `secret`, `config_url`, and (with `--token`) a live code. **Treat
the secret like a password.** To read a token for an already-enrolled device
without rotating, use `scripts/otp_token.py` instead.

### `export_analysis_set` — audited de-identification chokepoint (Slice 01)

Writes one CSV per model to `analysis_sets/<version>/` plus a `manifest.json`
(row counts, per-file SHA-256, per-column type expectations). Every date is
converted to an integer **day-offset from the recipient's `kt_date`**
(transplant = day 0) — no calendar date or date-of-birth ever leaves.

```bash
python manage.py export_analysis_set v0.1
python manage.py export_analysis_set v0.1 --outdir analysis_sets
```

| Argument    | Description |
|-------------|-------------|
| `version`   | Snapshot version, e.g. `v0.1` (required). |
| `--outdir`  | Output base directory (default: `analysis_sets`). |

**Fail-closed guarantees:**
- **Refuses to overwrite** an already-frozen version.
- **Emits nothing** if any identifier-shaped value (name, MRN, address, or raw
  calendar date) is detected in the staged output — the whole export aborts for
  a human to inspect, which is the safe direction for a de-id gate.

### `ingest_genotyping` — genotyping pipeline result loader (Slice 10)

The system-of-record loader for one manually-run genotyping pipeline run
(BioEdit/BLASTn/MAFFT are run outside the system; this records provenance).

```bash
python manage.py ingest_genotyping path/to/manifest.json
```

| Argument   | Description |
|------------|-------------|
| `manifest` | Path to the run's `manifest.json` (required). |

**Guarantees:**
- **All-or-nothing** — the whole import runs in one transaction; a mid-import
  failure rolls back with no half-written rows (and unwinds any content files).
- **Idempotent** — keyed by the input-manifest SHA-256; re-running a run that is
  already ingested does nothing and duplicates nothing.
- **Content-addressed** — each raw file is stored under `MEDIA_ROOT` named by its
  SHA-256, so identical bytes deduplicate.
- Closes the Slice-09 tube→analysis custody link by pointing the named
  `ConsumptionEvent` at the created `PipelineRun`.

Manifest schema (files referenced relative to the manifest's directory):

```json
{
  "tool_versions": "BioEdit 7.2; MAFFT 7.5",
  "reference_set": {"name": "Ross 2020", "citation": "...",
                    "content_sha256": "<hex>", "accessions": ["..."]},
  "results": [{"aliquot_id": 1, "consumption_event_id": 5,
               "assay_type": "sanger", "entered_by": "<username>",
               "calls": ["..."], "sanger": ["..."], "qpcr": ["..."]}]
}
```

---

## Related helper scripts (not `manage.py` subcommands)

- `scripts/otp_token.py` — print the current TOTP token for a device (`--reset`
  clears a throttle lockout). Use this to log in once a device is enrolled.
- `scripts/backpressure.py`, `scripts/run_slices.sh` — see `scripts/`.
