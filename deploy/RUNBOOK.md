# RENOVA operations runbook (Slice 15)

The human procedures behind `deploy/CHECKLIST.md`. The checklist installs the
machinery; this runbook is what people *do* — reboots, drills, custody, and the
sign-off that clears the box for real patient data.

**Roles**
- **DPO** — SPMC Data Protection Officer (IHOMPS); owns the RA 10173 posture sign-off.
- **Data Manager (DM)** — the project bioinformatician; the only person with DB superuser (console) and routine data entry.
- **Operator** — runs the box day to day (backups, updates, reboots). May be the DM.
- **Co-DM** — bus-factor custodian; holds sealed credentials off-site; **no routine data-entry account**.

---

## §4 — Power, updates, and operator-gated reboots

**Why manual reboots.** This is a LUKS box: on boot it stops at a passphrase prompt
until a human types it at the console. So it must **never auto-reboot** — an
unattended reboot would leave RENOVA down at a prompt nobody is standing at.
Security updates auto-install (they patch without rebooting); the reboot is yours.

**When "reboot required" appears** (after a kernel/security update):
1. Pick a time you can be physically at the box.
2. Announce brief downtime to the DM.
3. `sudo systemctl start renova-backup.service` — take a fresh backup first.
4. `sudo reboot`.
5. Enter the LUKS passphrase at the console.
6. Confirm recovery: `systemctl is-active postgresql renova` → `active`; open `https://127.0.0.1/`.

**Power.** The battery is the UPS. Test quarterly by unplugging; the box must keep
serving. If Ubuntu warns of a failing battery, treat it as a UPS failure — replace
before it can drop Postgres mid-write.

**Lid / unattended (security).** The lid-close handler is disabled so the box keeps
running as a server (`logind-renova.conf`). The counterpart rule: **when you leave
it unattended, power it fully OFF and lock it in a room.** Suspend/sleep keeps the
LUKS key in RAM — a sleeping laptop is *not* protected. OFF = protected.

## §5 — Backup custody and the quarterly restore drill

**Three parts, public-key encryption.** `backup.sh` writes three encrypted artifacts
(DB dump, MEDIA_ROOT, secrets) to the backup target (Drive 1), encrypted with GPG
**asymmetrically** to `RENOVA_BACKUP_GPG_RECIPIENT`. The box holds only the *public*
key, so a stolen or compromised running box **cannot decrypt its own backups**. The
*private* key that decrypts them is escrowed off-box in sealed custody (§8) and only
imported on the drill/recovery machine. A weekly copy of the `*.gpg` files goes to
**off-site Drive 2** (§8 custody).

To restore, the drill machine points `RENOVA_BACKUP_GNUPGHOME` at a keyring holding
the imported private key (and `RENOVA_BACKUP_GPG_PASSPHRASE_FILE` if it is
passphrase-protected).

**Quarterly restore drill (a backup you have never restored is not a backup):**
1. `sudo deploy/bin/restore-drill.sh /mnt/backup/renova/db-<latest>.dump.gpg`
2. Confirm it ends with `RESTORE DRILL PASSED` (decrypt + restore + pgcrypto verified).
3. Record it in the log below.

| Drill date (UTC) | Backup tested (filename) | Result | Run by |
|---|---|---|---|
| _pending first drill_ | | | |

## §7 — Audit integrity

- **Least-privilege DB** — `sql/02-restrict-superuser.sql` keeps the app off
  superuser so it cannot rewrite the `simple_history` audit trail. Superuser stays
  with `postgres`, reachable only by the DM at the console.
- **Trustworthy clock** — `timedatectl set-ntp true`. Audit timestamps are
  worthless if the clock drifts; NTP keeps them honest.
- **Immutable history export (quarterly, off-site):** export the append-only
  history into the backup set so a later DB compromise cannot rewrite the past.
  ```sh
  sudo -u postgres pg_dump --format=custom --table='*_history' -d renova \
      -f /mnt/backup/renova/history-$(date -u +%Y%m%dT%H%M%SZ).dump
  ```
  Encrypt it into the off-site Drive 2 set alongside the nightly backups. Log the date here.

| History-export date (UTC) | Sent off-site? | Run by |
|---|---|---|
| _pending first export_ | | |

## §8 — Sealed credentials + bus-factor

**What is sealed** (each in its own signed, dated envelope):
1. The **LUKS disk passphrase** — without it a powered-off box is unrecoverable.
2. The **backup GPG private key** (exported, e.g. `renova-backup-private.asc`, plus its
   passphrase) — without it the backups are permanently unrecoverable. The live box
   never holds this; it is the whole point of the asymmetric scheme.

**Custody:** the Co-DM holds the sealed envelopes **off-site**, on a custody path
separate from both the box and Drive 1. The Co-DM has **no routine data-entry
account** — custody is not a login.

**Bus-factor invocation** (the DM/Operator is unavailable and the box or its
backups must be recovered):
1. Two people present: the Co-DM and a DPO-authorised witness.
2. Record who, when, and why (the DPO logs it for the RA 10173 trail).
3. Open only the envelope needed (disk passphrase to unlock the box; backup key to
   restore off-site). Do not open both if only one is needed.
4. After use, **re-seal with fresh material**: rotate the exposed secret (new LUKS
   passphrase or new backup key), re-seal, re-date, re-sign, return to custody.

**Test it:** at standup, the Co-DM performs a dry-run — locate the envelopes,
confirm they are sealed and dated, and read this procedure aloud with the DM.

---

## Sign-off — the real "done"

The box is **NOT cleared to hold real patient data** until all four sign. Each
signer confirms their column's Verifies in `deploy/CHECKLIST.md` pass on the real
box.

| Role | Confirms | Name | Signature | Date |
|---|---|---|---|---|
| **DPO** | RA 10173 posture: de-id boundary intact, secrets/audit/custody adequate (§1, §7, §8) | | | |
| **Data Manager** | App + DB correct, least-privilege role, audit trail intact (§1, §3, §7) | | | |
| **Operator** | Firewall/SSH, updates, power, backups, monitoring all verified (§2, §4, §5, §6) | | | |
| **Co-DM** | Sealed envelopes in off-site custody; bus-factor procedure understood (§8) | | | |

Until every row is signed, treat the deployment as Phase 3 (runs, not cleared).
