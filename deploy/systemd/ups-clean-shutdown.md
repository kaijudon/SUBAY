# SUBAY — UPS + clean-shutdown daemon (Slice 15, AC4)

**WHY:** Davao mains power is unreliable. A hard power-cut mid-write can corrupt
Postgres (torn pages, lost WAL). A UPS buys minutes; a shutdown daemon spends those
minutes doing a *clean* `systemctl poweroff` so Postgres flushes and closes properly.

## What to install on the real box (HITL)

Use **NUT** (Network UPS Tools), the standard Linux UPS daemon.

```sh
sudo apt install nut
```

### `/etc/nut/ups.conf` — describe the UPS

```ini
[subay-ups]
    driver = usbhid-ups        # most USB consumer UPSes; confirm with `nut-scanner`
    port = auto
    desc = "SUBAY workstation UPS"
```

### `/etc/nut/upsmon.conf` — when to shut down

```ini
MONITOR subay-ups@localhost 1 upsmon <password-from-/etc/subay/subay.env> master
# On low battery, NUT calls SHUTDOWNCMD. Give Postgres a clean stop, then power off.
SHUTDOWNCMD "/bin/systemctl poweroff"
# Trigger shutdown while charge remains for a clean flush (don't wait for 0%).
```

Order matters: systemd already orders `postgresql.service` before `poweroff.target`,
so a `systemctl poweroff` stops gunicorn (`subay.service`) and Postgres cleanly before
the UPS battery dies. **Test it**: pull mains power and confirm the box powers off by
itself with the database intact (restore-drill afterwards if unsure).

After power returns the box stays OFF (no auto-power-on) — a human powers it up and
unlocks LUKS at the console, same gate as a reboot (AC4).
