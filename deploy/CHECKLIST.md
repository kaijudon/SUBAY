# SUBAY production-hardening checklist (Slice 15)

Work this **top to bottom on the real SPMC box**. Every item has a **Verify** — do
not tick it until the Verify passes. This is the checklist `LAPTOP-DEPLOY.md`
Phase 4 sends you to. The plain-language *why* for each section is in that guide's
Phase 4 table; the human procedures (reboots, sealed envelopes, drills) are in
`deploy/RUNBOOK.md`.

> Prerequisites: Phases 1–3 of `LAPTOP-DEPLOY.md` are done (LUKS on, app runs,
> secrets in `/etc/subay/subay.env`), and the Slice 0 systemd + nginx standup in
> `deploy/README.md` is complete (gunicorn socket + nginx on 127.0.0.1).
>
> Paths below assume the conda env at `/opt/conda/envs/subay_env` (per
> `LAPTOP-DEPLOY.md` §2.2). If yours differs, adjust.

Load secrets into your shell for the psql/manage steps (root reads the 0600 file):
```sh
cd /opt/subay
set -a; source <(sudo cat /etc/subay/subay.env); set +a
```

---

## §1 — Secrets locked + pgcrypto defense-in-depth  (`sql/01-pgcrypto.sql`)

- [ ] Secrets live only in the root-owned `0600` `/etc/subay/subay.env` (Phase 3.3), never in the repo.
      **Verify:** `stat -c '%U %a' /etc/subay/subay.env` → `root 600`.
- [ ] pgcrypto extension is installed in the `subay` DB.
      ```sh
      sudo -u postgres psql -d subay -f deploy/sql/01-pgcrypto.sql
      ```
      **Verify:** `sudo -u postgres psql -d subay -c "\dx pgcrypto"` lists the extension,
      and the run prints `pgcrypto self-test OK`.

> Read the header of `sql/01-pgcrypto.sql`: the load-bearing at-rest control is LUKS
> (Phase 1); pgcrypto here protects the **off-machine backup** and is verified by the
> quarterly restore drill (§5). Column-level encryption is deferred (DEC-024).

## §2 — Firewall + SSH lockout  (`firewall/ufw-setup.sh`)

- [ ] Edit `ADMIN_SUBNET` (and `SSH_ENABLED`) at the top of `firewall/ufw-setup.sh`, then run it.
      ```sh
      sudo deploy/firewall/ufw-setup.sh
      ```
      **Verify:** `sudo ufw status verbose` → default deny incoming; port 22 only from your admin subnet; nothing else.
- [ ] Key-only SSH (skip if you never SSH in and set `SSH_ENABLED=0`). Put your public key in `~/.ssh/authorized_keys` FIRST.
      ```sh
      sudo cp deploy/firewall/sshd-hardening.conf /etc/ssh/sshd_config.d/10-subay.conf
      sudo sshd -t && sudo systemctl restart ssh
      ```
      **Verify:** `sudo sshd -T | grep -E 'passwordauthentication|permitrootlogin'` → both `no`.
- [ ] fail2ban guarding SSH.
      ```sh
      sudo apt install -y fail2ban
      sudo cp deploy/firewall/fail2ban-jail.local /etc/fail2ban/jail.local   # edit ignoreip subnet
      sudo systemctl enable --now fail2ban
      ```
      **Verify:** `sudo fail2ban-client status sshd` prints a jail (0 banned is fine).

## §3 — Safe database changes  (`bin/safe-migrate.sh`)

- [ ] Use the wrapper for every migration from now on — it `pg_dump`s first and rehearses data migrations on a scratch DB.
      ```sh
      sudo install -m 755 deploy/bin/safe-migrate.sh /usr/local/bin/subay-safe-migrate
      ```
      **Verify:** run it against the current (already-migrated) DB. Let root read the
      0600 secrets file directly and run the wrapper in the same shell (works regardless
      of the sudo `setenv` policy — `sudo -E` is silently ignored on a default install):
      ```sh
      sudo bash -c 'set -a; source /etc/subay/subay.env; set +a; subay-safe-migrate'
      ```
      It reports "additive-only" (nothing pending) and a pre-migrate `.dump` appears under `/var/backups/subay/pre-migrate/`.

## §4 — Updates, power, lid  (`apt/…`, RUNBOOK §4)

- [ ] Auto security updates, **no** auto-reboot.
      ```sh
      sudo apt install -y unattended-upgrades
      sudo cp deploy/apt/50unattended-upgrades-subay /etc/apt/apt.conf.d/
      sudo cp deploy/apt/20auto-upgrades /etc/apt/apt.conf.d/
      ```
      **Verify:** `sudo unattended-upgrade --dry-run` runs; the config sets `Automatic-Reboot "false"`.
- [ ] Laptop keeps running with the lid closed.
      ```sh
      sudo install -d /etc/systemd/logind.conf.d
      sudo cp deploy/systemd/logind-subay.conf /etc/systemd/logind.conf.d/subay.conf
      sudo systemctl restart systemd-logind
      ```
      **Verify:** close the lid — the box stays up (SSH/console still responds).
- [ ] Battery = UPS: unplug and confirm it keeps serving. Read RUNBOOK §4 for operator-gated reboots.
      **Verify:** app still answers on `https://127.0.0.1/` on battery.
- [ ] Clean-shutdown daemon on the UPS (never let a power-cut tear a Postgres write). Follow `deploy/systemd/ups-clean-shutdown.md` (NUT).
      **Verify:** `upsc subay-ups` reports the UPS; a simulated low-battery triggers `systemctl poweroff`.
- [ ] Operator gets pushed a notice when a reboot is pending (updates never auto-reboot this LUKS box).
      ```sh
      sudo cp deploy/bin/notify-operator.sh /opt/subay/deploy/bin/   # already in repo; ensure executable
      sudo cp deploy/systemd/subay-reboot-required.{service,timer} /etc/systemd/system/
      sudo systemctl daemon-reload && sudo systemctl enable --now subay-reboot-required.timer
      ```
      **Verify:** `sudo touch /run/reboot-required` then `sudo systemctl start subay-reboot-required.service` → you receive one PHI-free "reboot-required" alert.

## §5 — Backups + restore drill  (`bin/backup.sh`, `bin/restore-drill.sh`)

- [ ] Generate the backup GPG keypair ONCE, on a machine that is NOT the live box (asymmetric: the box only gets the public key).
      ```sh
      # On the DM's admin machine (or an air-gapped one):
      gpg --batch --gen-key <<'KEY'
        %no-protection
        Key-Type: RSA
        Key-Length: 4096
        Name-Real: SUBAY Backup
        Name-Email: subay-backup@spmc.local
        Expire-Date: 0
      KEY
      gpg --armor --export        subay-backup@spmc.local > subay-backup-public.asc
      gpg --armor --export-secret-keys subay-backup@spmc.local > subay-backup-private.asc   # -> sealed custody, §8
      ```
      **On the live box**, import ONLY the public key (the box must never hold the private half):
      ```sh
      sudo install -d -m 700 /var/lib/subay
      gpg --import subay-backup-public.asc
      ```
      **Verify:** `gpg --list-keys subay-backup@spmc.local` shows the key; `gpg --list-secret-keys` on the box shows **nothing** for it.
- [ ] Recreate the sandbox dirs on every boot so the backup/history-export units can build their ProtectSystem=strict namespace (a missing ReadWritePaths= dir kills them at status=226/NAMESPACE). This supersedes the ad-hoc `install -d` steps above.
      ```sh
      sudo cp deploy/systemd/tmpfiles.d/subay.conf /etc/tmpfiles.d/subay.conf
      sudo systemd-tmpfiles --create /etc/tmpfiles.d/subay.conf   # create now, not just next boot
      ```
      **Verify:** `/var/lib/subay` (root) and `/var/backups/subay{,/history}` (subay) exist with mode 700.
- [ ] Install and schedule the nightly backup.
      ```sh
      sudo cp deploy/systemd/subay-backup.{service,timer} /etc/systemd/system/
      sudo systemctl daemon-reload && sudo systemctl enable --now subay-backup.timer
      sudo systemctl start subay-backup.service    # first run now
      ```
      **Verify:** three `*.gpg` files + a `manifest-*.sha256` in the backup dest; `/var/lib/subay/last-backup.stamp` exists.
- [ ] Prove the backup restores AND pgcrypto decrypts (do this now, then quarterly). The drill machine needs the escrowed **private** key imported (`SUBAY_BACKUP_GNUPGHOME` points at that keyring; set `SUBAY_BACKUP_GPG_PASSPHRASE_FILE` if the key has a passphrase).
      ```sh
      sudo SUBAY_BACKUP_GNUPGHOME=/root/.gnupg-restore \
        deploy/bin/restore-drill.sh /mnt/backup/subay/db-<TS>.dump.gpg
      ```
      **Verify:** ends with `RESTORE DRILL PASSED`. Log the date in RUNBOOK §5.
- [ ] Copy today's `*.gpg` to off-site Drive 2 custody (RUNBOOK §8).

## §6 — Alerts  (`bin/healthcheck.sh`)

- [ ] Set `SUBAY_ALERT_CMD` (how you get paged) and `SUBAY_HEARTBEAT_URL` (dead-man's switch) in the healthcheck unit, then install it.
      ```sh
      sudo cp deploy/systemd/subay-healthcheck.{service,timer} /etc/systemd/system/   # edit Environment= first
      sudo systemctl daemon-reload && sudo systemctl enable --now subay-healthcheck.timer
      ```
      **Verify:** `sudo systemctl start subay-healthcheck.service` then `journalctl -u subay-healthcheck -n 20` shows `healthy` (or a PHI-free alert). Trip it on purpose (stop nginx) → you get an alert with no patient data in it.

## §7 — Audit integrity + trustworthy clock  (`sql/02-restrict-superuser.sql`)

- [ ] App DB role is least-privilege (not a superuser).
      ```sh
      sudo -u postgres psql -d subay -f deploy/sql/02-restrict-superuser.sql
      ```
      **Verify:** `sudo -u postgres psql -d subay -c "\du subay"` → empty Attributes (no Superuser).
- [ ] Time is trustworthy (audit timestamps must not drift).
      ```sh
      sudo timedatectl set-ntp true
      ```
      **Verify:** `timedatectl` → `System clock synchronized: yes`, `NTP service: active`.
- [ ] Periodic tamper-evident history export scheduled (`bin/export-history.sh` → hash-chained, off-site immutable bucket).
      ```sh
      # Pre-create the output dir owned by the subay service user — the unit runs as
      # User=subay, which cannot mkdir under root-owned /var/backups (else it exits 1).
      sudo install -d -m 700 -o subay -g subay /var/backups/subay/history
      sudo cp deploy/systemd/subay-history-export.{service,timer} /etc/systemd/system/
      sudo systemctl daemon-reload && sudo systemctl enable --now subay-history-export.timer
      sudo systemctl start subay-history-export.service   # first run now
      ```
      **Verify:** a `history_<TS>.sql.gz` + a new line in `history_chain.log` appear under `/var/backups/subay/history`; the first export is pushed off-site to the object-lock bucket (RUNBOOK §7).

## §8 — Sealed envelopes + bus-factor  (RUNBOOK §8)

- [ ] LUKS passphrase + backup key sealed in envelopes, held by the Co-DM on a separate custody path.
      **Verify:** two sealed, dated, signed envelopes exist; the bus-factor procedure in RUNBOOK §8 is written and both parties have read it.
- [ ] Co-DM has custody access but **no routine data-entry account**.
      **Verify:** the Co-DM has no active Django login with data-entry rights.

---

## Done means signed

Ticking every box above makes the box **technically** hardened. It is **not cleared
for real patient data** until the sign-off table in `deploy/RUNBOOK.md` is filled by
the DPO, Data Manager, Operator, and Co-DM. That signature is the real "done".
