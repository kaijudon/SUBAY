# Slice 15 — SUBAY: Production hardening & operations

**Type:** HITL (physical SPMC workstation + DPO/operator sign-off + human custody procedures)
**Deep module:** none (systemd units, nginx/gunicorn config, wrapper scripts, cron — not Django-app code)
**User stories:** 80, 81, 82, 83, 84, 85, 86, 87, 88, 89

## Parent

PRD: `prd/CMV-KT_Research_Database_PRD.md`

## What to build

Defense-in-depth deployment for a single-operator localhost box in Davao where the real enemies are **silent failure and operational footguns** (auto-reboot into a locked disk, un-decryptable backups), not clever attackers. This is HITL: it needs the physical workstation, the DPO's RA 10173 posture sign-off, and human custody procedures, so it can't be merged AFK. It builds on slice 00's localhost/Unix-socket/systemd spine.

Scope (Topic #7-D D1–D10 + build-time checklist): app bound to `127.0.0.1` behind nginx-terminated HTTPS (locally-trusted cert) over a Unix socket; secrets in a root-owned `0600` env file via systemd; pgcrypto on sensitive columns as defense-in-depth over off-machine backups; key-only SSH (password + root login disabled, LAN-bound, fail2ban, UFW inbound 22 from the admin subnet only); a migration wrapper that always `pg_dump`s before `migrate`, applies additive migrations directly, and rehearses destructive/`RunPython` migrations on a scratch DB first; auto-installed security updates with **operator-gated** manual reboots (never auto-reboot a LUKS box into a hung passphrase prompt); manual LUKS passphrase unlock at console (key in the operator's head + sealed envelope via Co-DM) paired with a UPS + clean-shutdown daemon; a three-part backup (Postgres dump + encrypted `MEDIA_ROOT` + secrets incl. the pgcrypto key) with the key escrowed on a **separate custody path** and a quarterly restore drill that verifies pgcrypto decryption; push-on-failure monitoring (last-backup age, disk %, app health, SSH anomalies) with a dead-man's switch and **no PHI in alerts**; tamper-evident audit integrity (enforced NTP, Postgres superuser restricted to the Data Manager, periodic history export into immutable off-site backups); sealed-credentials + off-site Drive 2 custody with a documented bus-factor invocation procedure.

## Acceptance criteria

- [ ] App reachable only on `127.0.0.1` via nginx HTTPS over a Unix socket; secrets load from a root-owned `0600` systemd env file, never from repo/settings; pgcrypto encrypts sensitive columns.
- [ ] SSH is key-only (password + root login disabled), LAN-bound, with fail2ban and UFW allowing inbound 22 from the admin subnet only.
- [ ] The migration wrapper `pg_dump`s before every `migrate`, applies additive migrations directly, and rehearses `RunPython`/destructive migrations on a scratch DB first.
- [ ] Security updates auto-install but reboots are operator-gated; a UPS + clean-shutdown daemon protects Postgres from power-loss corruption; LUKS unlock is manual at console.
- [ ] The three-part backup runs (Postgres + encrypted `MEDIA_ROOT` + secrets/pgcrypto key), the key is escrowed on a separate custody path, and a quarterly restore drill verifies pgcrypto decryption end-to-end.
- [ ] Push-on-failure monitoring covers last-backup age, disk %, app health, and SSH anomalies, has a dead-man's switch, and carries no PHI in any alert.
- [ ] Audit integrity holds: enforced NTP, Postgres superuser restricted to the Data Manager, periodic history export into immutable off-site backups.
- [ ] Sealed-credentials + off-site Drive 2 custody exist with a written bus-factor invocation procedure that grants the Co-DM no routine data-entry access.

## Blocked by

- Blocked by Slice 00 (walking skeleton — extends its localhost/Unix-socket/systemd spine)
