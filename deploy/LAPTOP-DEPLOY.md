# RENOVA — Laptop Deploy Day (beginner-friendly)

One ordered page to turn a fresh laptop into the team's RENOVA workstation. Follow it
**top to bottom** — do not skip ahead. Each step says what to type, what you should see,
and how to know it worked.

> **Who this is for:** someone new to the command line. Commands you type are in grey
> boxes. After each, there's a **✅ Check** — do not move on until it passes.
>
> **When to stop and ask for help:** any time a Check fails, an `⚠️` step makes you
> nervous, or you see an error you don't understand. Stop, copy the exact error, ask.
> A half-finished deploy is safer than a wrong guess on a box that holds patient data.

**The big picture — 4 phases:**

```
Phase 1: Install Ubuntu + turn on disk encryption   (the foundation — do FIRST)
Phase 2: Get the code + set up the app              (makes RENOVA run)
Phase 3: Fill in the secrets + database             (makes it usable)
Phase 4: Harden the box (Slice 15)                  (makes it safe for patient data)
```

You are NOT done until Phase 4's sign-off table is filled. Phases 1–3 make it *run*;
Phase 4 makes it *safe*.

---

## Phase 1 — Ubuntu + disk encryption  ⚠️ DO THIS FIRST

Full-disk encryption (LUKS) can **only** be turned on while installing Ubuntu. You
cannot add it later without wiping the laptop. So it has to be step one.

1. Make a bootable Ubuntu **26.04 LTS Desktop** USB stick (use another computer +
   "Rufus" on Windows or "Startup Disk Creator" on Linux). Boot the laptop from it.
2. In the installer, choose **"Erase disk and install Ubuntu"**.
3. Click **"Advanced features"** → tick **"Encrypt the new Ubuntu installation"**
   (this is LUKS). Set a strong passphrase.

   > ⚠️ **Write this passphrase down on paper and keep it safe.** If you lose it, the
   > data is gone forever — that is the whole point of encryption. You will also seal a
   > copy in an envelope in Phase 4.
4. Finish the install. Reboot. You'll be asked for the encryption passphrase **every
   time the laptop powers on** — that's correct.
5. Log into the Ubuntu desktop.

**✅ Check:** the laptop boots, asks for a disk passphrase before the login screen.
That passphrase prompt = LUKS is working.

---

## Phase 2 — Get the code + set up the app (Slice 0)

Open the **Terminal** app (press the Super/Windows key, type "terminal", Enter).

### 2.1 — Install the basics

```sh
sudo apt update
sudo apt install -y git curl
```

`sudo` means "do this as administrator" — it will ask for your login password.

**✅ Check:** `git --version` prints a version number.

### 2.2 — Install Miniconda (runs the app's Python)

```sh
curl -o /tmp/miniconda.sh https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash /tmp/miniconda.sh -b -p /opt/conda
sudo ln -sf /opt/conda/bin/conda /usr/local/bin/conda
```

**✅ Check:** `conda --version` prints a version number.

### 2.3 — Download RENOVA

```sh
sudo git clone https://github.com/kaijudon/RENOVA.git /opt/renova
sudo chown -R "$USER" /opt/renova
cd /opt/renova
```

> You'll be asked for your GitHub username + a **personal access token** (not your
> password). If you don't have one: github.com → Settings → Developer settings →
> Personal access tokens → generate one with "repo" access.

**✅ Check:** `ls /opt/renova` shows folders like `deploy`, `renova`, `manage.py`.

### 2.4 — Build the app's environment

```sh
conda env create -f /opt/renova/environment.yml -p /opt/conda/envs/renova_env
```

This downloads everything the app needs — takes a few minutes.

**✅ Check:** the command ends without "error", and
`/opt/conda/envs/renova_env/bin/python --version` prints a Python version.

---

## Phase 3 — Secrets + database

### 3.1 — Install PostgreSQL (the database)

```sh
sudo apt install -y postgresql
sudo systemctl enable --now postgresql
```

**✅ Check:** `systemctl is-active postgresql` prints `active`.

### 3.2 — Make the database + app login

```sh
sudo -u postgres psql -c "CREATE DATABASE renova;"
sudo -u postgres psql -c "CREATE ROLE renova LOGIN PASSWORD 'CHANGE-ME-STRONG';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE renova TO renova;"
```

> Replace `CHANGE-ME-STRONG` with a real password. Make one with:
> `openssl rand -base64 24` — copy the output, use it here, and again in step 3.3.

**✅ Check:** none of those three commands printed an error (each prints `CREATE
DATABASE` / `CREATE ROLE` / `GRANT`).

### 3.3 — Create the secrets file

This file holds all the passwords/keys. It lives **outside** the code and is never
shared. First generate the values:

```sh
echo "DJANGO_SECRET_KEY: "; python3 -c 'import secrets; print(secrets.token_urlsafe(64))'
echo "RENOVA_PGCRYPTO_KEY: "; openssl rand -base64 48
```

Now make the file:

```sh
sudo install -d -m 700 /etc/renova
sudo install -m 600 /opt/renova/deploy/renova.env.example /etc/renova/renova.env
sudo nano /etc/renova/renova.env
```

`nano` is a simple text editor. Fill in the real values you generated (the database
password from 3.2 goes into `DATABASE_URL`). Save with **Ctrl+O**, Enter, then exit with
**Ctrl+X**.

> ⚠️ Never paste this file's contents into chat, email, or git. Anyone who reads it owns
> the whole system.

**✅ Check:** `stat -c '%U %a' /etc/renova/renova.env` prints exactly `root 600`.

### 3.4 — Set up the database tables + your admin login

```sh
cd /opt/renova
set -a; source /etc/renova/renova.env; set +a
/opt/conda/envs/renova_env/bin/python manage.py migrate
/opt/conda/envs/renova_env/bin/python manage.py createsuperuser
```

Follow the prompts to make your admin username + password.

**✅ Check:** `migrate` ends with "OK"s, and `createsuperuser` says the user was created.

### 3.5 — First run (test it works before hardening)

```sh
/opt/conda/envs/renova_env/bin/python manage.py runserver 127.0.0.1:8000
```

Open Firefox → `http://127.0.0.1:8000/admin/`.

> You'll hit a two-factor (OTP) prompt. First time, you need to enroll a code — ask for
> the "TOTP bootstrap" steps (same as we did on the dev box) if it blocks you.

**✅ Check:** you can log into `/admin/` and see the RENOVA interface. Press **Ctrl+C** in
the terminal to stop the test server.

> This `runserver` is just a test. The real, always-on service is set up by the Slice 0
> systemd steps in `deploy/README.md` (gunicorn + nginx). Do those next, then continue to
> Phase 4. If unsure, ask for help wiring up systemd + nginx.

---

## Phase 4 — Harden the box (Slice 15)

Now make it safe for real patient data. Open **`deploy/CHECKLIST.md`** and work it top to
bottom — every item there has a Verify. Below is the plain-language map of what each
section does and why. **Do the sections in order.**

| Section | In plain words | Key file |
|---|---|---|
| **§1** | Lock down secrets + encrypt sensitive DB columns | `deploy/sql/01-pgcrypto.sql` |
| **§2** | Firewall + SSH lockout so outsiders can't reach the box | `deploy/firewall/ufw-setup.sh` |
| **§3** | Safe way to change the database without losing data | `deploy/bin/safe-migrate.sh` |
| **§4** | Auto-updates, battery shutdown, lid-stays-open | `deploy/apt/50unattended-upgrades-renova`, RUNBOOK §4 |
| **§5** | Nightly backups + a test that they actually restore | `deploy/bin/backup.sh` |
| **§6** | Alerts you when something breaks (no patient data in alerts) | `deploy/bin/healthcheck.sh` |
| **§7** | Tamper-proof audit history + trustworthy clock | `deploy/sql/02-restrict-superuser.sql` |
| **§8** | Sealed envelopes + a second person (bus-factor) | RUNBOOK §8 |

**Laptop-specific reminders (already in RUNBOOK §4/§8):**
- Stop the laptop suspending when the lid closes (it must keep running backups).
- Use the battery as your backup power — test by unplugging.
- ⚠️ When unattended, power the laptop **OFF** (not sleep) and lock it in a room.
  Sleep keeps the encryption key in memory — a sleeping laptop is NOT protected.

### The finish line

Phase 4 ends with the **sign-off table** in `deploy/RUNBOOK.md`. Until the DPO, Data
Manager, Operator, and Co-DM have all signed, the laptop is **not cleared to hold real
patient data**. That signature is the real "done".

---

## If something goes wrong

- A Check failed → stop, copy the exact red text, ask before continuing.
- You typed a command and nothing happened → it may still be running; wait, or press
  Ctrl+C and try again.
- ⚠️ Never run a command you don't understand on this box just to "get past" an error.
- Forgot the disk passphrase / locked out → that's what the sealed envelope (Phase 4 §8)
  is for. If there's no envelope yet and it's lost, the data is unrecoverable.

You do not have to do all four phases in one day. Good stopping points: end of Phase 2,
end of Phase 3. Just never leave it at Phase 3 (running but unhardened) holding real
patient data.
