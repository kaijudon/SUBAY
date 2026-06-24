# RENOVA — Slice 15 build-time deployment checklist

Tick on the real box, in order. Each maps to a RUNBOOK section + an artifact. Do not
mark an item done until its **Verify** passes. HITL: a human runs and signs these.

- [ ] **§1 App + secrets + pgcrypto**
  - [ ] `ss -tlnp` shows the app on `127.0.0.1` only (no public interface)
  - [ ] `stat -c '%U %a' /etc/renova/renova.env` → `root 600`
  - [ ] `deploy/sql/01-pgcrypto.sql` applied; decryption round-trip verified before any plaintext column dropped
- [ ] **§2 SSH**
  - [ ] `sshd_hardening.conf` installed; password + root login refused
  - [ ] `ufw-setup.sh` run with real `ADMIN_SUBNET`; inbound default-deny; 22 from admins only; no 80/443 on LAN
  - [ ] fail2ban active (`systemctl is-active fail2ban`)
- [ ] **§3 Migrations** — `safe-migrate.sh` is the only migrate path; destructive migrations rehearse on scratch (exit 2) before production
- [ ] **§4 Updates / power / LUKS**
  - [ ] `50unattended-upgrades-renova` installed; `Automatic-Reboot "false"` confirmed
  - [ ] `renova-reboot-required.timer` enabled
  - [ ] LUKS unlock tested at console; passphrase in operator's head + sealed envelope (§8)
  - [ ] UPS (NUT) clean-shutdown tested by pulling mains power; DB intact
- [ ] **§5 Backup + drill**
  - [ ] `renova-backup.timer` enabled; nightly run produces all 3 parts; secrets/key on separate `KEY_DEST` mount
  - [ ] `restore-drill.sh` passes; pgcrypto decrypts end-to-end; logged in RUNBOOK §5 table
- [ ] **§6 Monitoring**
  - [ ] `renova-healthcheck.timer` enabled; a forced failure pushes an alert
  - [ ] dead-man's switch pings on healthy runs; stopping them alerts externally
  - [ ] alert text reviewed — contains NO PHI
- [ ] **§7 Audit integrity**
  - [ ] chrony enforced, single upstream, no backward steps
  - [ ] `02-restrict-superuser.sql` applied; superuser = Data Manager only; app uses `renova` role
  - [ ] `renova-history-export.timer` enabled; exports hash-chained to object-lock off-site bucket
- [ ] **§8 Sealed credentials / bus-factor**
  - [ ] all four secrets sealed in tamper-evident envelopes, Co-DM off-site custody
  - [ ] written bus-factor invocation procedure on file; Co-DM has no routine data access
- [ ] **Sign-off** — RUNBOOK sign-off table complete (DPO + Data Manager + Operator + Co-DM)
