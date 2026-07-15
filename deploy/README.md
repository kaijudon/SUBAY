# SUBAY deploy spine (Slice 0 artifacts)

These are the deployment templates for the single SPMC-sited workstation. They are
committed as artifacts; **standing them up on the real box is the HITL checkpoint
handled in Slice 15 (production hardening & operations)** — it needs the physical
machine, the DPO's RA 10173 sign-off, and human custody procedures, so it is not
merged AFK.

## What Slice 0 locks in

- App served by **gunicorn over a Unix socket** (`gunicorn.conf.py`) — no TCP port.
- **nginx** terminates HTTPS and binds **`127.0.0.1` only** (`nginx-subay.conf`) —
  the app is unreachable from any network interface.
- Secrets come from a **root-owned `0600` systemd `EnvironmentFile`**
  (`subay.service` + `subay.env.example`), never from the repo or `settings.py`.

## Install sketch (run on the real box, as the HITL checkpoint)

```sh
# 1. Code at /opt/subay (owned by the subay service user); conda env at
#    /opt/conda/envs/subay_env:
sudo conda env create -f /opt/subay/environment.yml -p /opt/conda/envs/subay_env
# 2. Secrets:
sudo install -d -m 700 /etc/subay
sudo install -m 600 deploy/subay.env.example /etc/subay/subay.env   # then edit
# 3. Locally-trusted TLS cert into /etc/subay/tls/.
# 4. Services:
sudo cp deploy/subay.service /etc/systemd/system/
sudo cp deploy/nginx-subay.conf /etc/nginx/sites-available/subay
sudo ln -s /etc/nginx/sites-available/subay /etc/nginx/sites-enabled/
sudo systemctl daemon-reload && sudo systemctl enable --now subay
sudo nginx -t && sudo systemctl reload nginx
# 5. /opt/conda/envs/subay_env/bin/python manage.py collectstatic --noinput
```

## Local development (no nginx/systemd)

```sh
conda run -n subay_env python manage.py migrate
conda run -n subay_env python manage.py runserver 127.0.0.1:8000
```

Deferred to Slice 15: LUKS full-disk, pgcrypto on sensitive columns, key-only SSH
+ fail2ban + UFW, the pg_dump-before-migrate wrapper, operator-gated reboots + UPS,
the three-part backup with a quarterly restore drill, push-on-failure monitoring,
and the sealed-credentials bus-factor procedure.
