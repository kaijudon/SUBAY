# RENOVA — Production Hardening & Operations Runbook (Slice 15)

**Status: HITL. NOT merged AFK.** Standing this up requires the physical SPMC
workstation, the DPO's RA 10173 posture sign-off, and human custody of keys and
passphrases. These artifacts are *drafts* — a human executes and signs off each step
on the real box. Real secrets/keys are NEVER written here; placeholders live in
`renova.env.example` and are filled only in the root-owned `0600` `/etc/renova/renova.env`.

This runbook extends the Slice 00 spine (`deploy/README.md`): gunicorn-over-Unix-socket,
nginx HTTPS on `127.0.0.1`, systemd secrets file. The sections below map 1:1 to the
Slice 15 acceptance criteria.

---

## §1 — App reachability + secrets + pgcrypto (AC1)

- App answers only on `127.0.0.1` via nginx HTTPS over the Unix socket (Slice 00).
  Verify: `ss -tlnp | grep -v 127.0.0.1` shows the app on NO public interface.
- Secrets load from `/etc/renova/renova.env` (root:root, `0600`) via systemd
  `EnvironmentFile` — never repo/settings. Verify: `stat -c '%U %a' /etc/renova/renova.env`
  → `root 600`.
- pgcrypto encrypts the sensitive admin-store columns (not the de-id export, which is
  already day-offsets + string IDs): run `deploy/sql/01-pgcrypto.sql`, confirm with the
  DPO which columns, verify decryption round-trips before dropping any plaintext column.

## §2 — SSH lockdown (AC2)

1. Install `deploy/ssh/sshd_hardening.conf` → `/etc/ssh/sshd_config.d/10-renova.conf`;
   set `ListenAddress`/`AllowUsers` to the real LAN IP + admin account; `sshd -t && systemctl reload ssh`.
2. Run `deploy/firewall/ufw-setup.sh` with the real `ADMIN_SUBNET` (default-deny inbound;
   only SSH/22 from admins; NO 80/443 from the LAN).
3. Install `deploy/fail2ban/jail.local`; `systemctl enable --now fail2ban`.
- Verify: password login refused, root login refused, port 22 unreachable from outside
  the admin subnet.

## §3 — Safe migrations (AC3)

- Always migrate via `deploy/bin/safe-migrate.sh` — it `pg_dump`s first, applies
  additive migrations directly, and REHEARSES `RunPython`/destructive migrations on a
  scratch DB (exit 2) for human review before they ever touch production.
- Never run `manage.py migrate` directly on the box for a destructive change.

## §4 — Updates, power, LUKS unlock (AC4)

- **Auto-install, never auto-reboot:** install `deploy/apt/50unattended-upgrades-renova`.
  Reboots are operator-gated: `renova-reboot-required.timer` pushes a notice; a human
  reboots and unlocks LUKS at the console.
- **LUKS:** full-disk encryption; the passphrase is in the operator's head **and** in a
  sealed envelope held by the Co-DM (§8). The box NEVER stores the passphrase. After any
  power event the box stays off until a human unlocks it at the console.
- **UPS + clean shutdown:** follow `deploy/systemd/ups-clean-shutdown.md` (NUT). Test by
  pulling mains power and confirming a clean self-powered-off with the DB intact.

## §5 — Three-part backup + quarterly restore drill (AC5)

- `renova-backup.timer` runs `deploy/bin/backup.sh` nightly: (1) Postgres dump,
  (2) GPG-encrypted `MEDIA_ROOT`, (3) GPG-encrypted secrets+pgcrypto key to a SEPARATE
  custody mount (`KEY_DEST`). Off-site copy to Drive 2 per §8 custody.
- **Quarterly:** run `deploy/bin/restore-drill.sh <dump> <secrets-archive>`. It restores
  to a throwaway DB and proves pgcrypto DECRYPTS end-to-end with the escrowed key. Record
  date + result in the drill log below. An untested backup does not count as a backup.

  | Quarter | Date run | Restored OK | pgcrypto decrypt OK | By | Notes |
  |---------|----------|-------------|---------------------|----|-------|
  |         |          |             |                     |    |       |

## §6 — Push-on-failure monitoring + dead-man's switch (AC6)

- `renova-healthcheck.timer` runs `deploy/bin/healthcheck.sh` every 15 min: last-backup
  age, disk %, app health, SSH-anomaly count. PUSHES via `notify-operator.sh` only on a
  problem. On a healthy run it pings `RENOVA_DEADMAN_URL`; if those pings STOP, the
  external watcher alerts (a dead box can't alert for itself).
- **No PHI in any alert** — senders pass counts/ages/percentages/state only. Audit the
  alert text periodically.

## §7 — Audit integrity (AC7)

- **NTP:** install chrony, single trusted upstream, `makestep` disabled in steady state
  so audit timestamps never jump backward.
- **Superuser:** run `deploy/sql/02-restrict-superuser.sql`; confirm Postgres superuser
  is exactly the named Data Manager; the app connects as the least-privilege `renova` role.
- **Immutable history:** `renova-history-export.timer` runs `export-history.sh` weekly,
  hash-chaining each export and pushing to an object-lock (write-once) off-site bucket so
  a changed past is detectable.

## §8 — Sealed credentials + bus-factor (AC8)

- **Sealed credentials:** LUKS passphrase, pgcrypto key, backup GPG key, and DB superuser
  password are written once, sealed in tamper-evident envelopes, and held by the Co-DM
  off-site (Drive 2 custody). The operator holds the working copies; the Co-DM holds the
  sealed recovery copies.
- **Bus-factor invocation procedure** (operator unavailable):
  1. Two named custodians (Data Manager delegate + DPO) jointly authorize recovery in
     writing.
  2. Retrieve the sealed envelope from Co-DM custody; log the seal break (date, who, why).
  3. Restore from the latest backup + key escrow per §5; run a restore drill to confirm.
  4. Rotate every recovered secret afterward and re-seal new envelopes.
  - The Co-DM gets **no routine data-entry access** — custody is recovery-only.

---

### Sign-off (HITL — required before production use)

| Item | Owner | Date | Signature |
|------|-------|------|-----------|
| DPO RA 10173 posture review | DPO | | |
| Physical workstation hardened (§1–§4) | Data Manager | | |
| Backup + restore drill passed (§5) | Operator | | |
| Monitoring live, alerts PHI-free (§6) | Operator | | |
| Bus-factor envelopes sealed + custody confirmed (§8) | Co-DM | | |
