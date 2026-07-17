# AFK data-entry tester - daily resume schedule (T4 / #15)

The data-entry tester is an AFK loop: it drives the rendered SUBAY admin, files
`afk-data-entry` GitHub issues, and re-runs. This wiring makes it **resume itself
unattended** so it keeps burning through the loop without a human kicking it off.

## Why 21:00 UTC

21:00 UTC (05:00 PHT) is the Claude **usage-limit reset**, not an arbitrary daily
time. Starting a window the instant the limit resets maximises how many
back-to-back iterations run before the next reset. The pipeline
(`data-entry-tester-pipeline.mts`) iterates with **no sleep or cooldown between
iterations** - the usage limit is the only thing that stops a window
(`MAX_ITERATIONS_PER_WINDOW` is just a runaway guard, set well above what one
reset-to-reset window can afford).

## Mechanism

The pipeline needs the **local Docker daemon** (sandcastle runs the tester in a
container on this workstation), so the schedule is an OS-level **systemd user
timer** on the box - not a cloud/session scheduler, which cannot reach local
Docker. Files:

- `systemd/afk-data-entry-resume.timer` - `OnCalendar=*-*-* 21:00:00 UTC`,
  `Persistent=true` (a reset missed while the box was off runs at next boot).
- `systemd/afk-data-entry-resume.service` - oneshot that runs the runner.
- `run-daily-resume.sh` - loads `.sandcastle/.env` secrets, runs the pipeline.

## Install / unwind

```sh
.sandcastle/install-schedule.sh        # substitutes the repo path, enables the timer
loginctl enable-linger "$USER"         # once, so it runs while logged out
.sandcastle/uninstall-schedule.sh      # remove it - touches NO app code
```

Inspect / trigger manually:

```sh
systemctl --user list-timers afk-data-entry-resume.timer --all
systemctl --user start afk-data-entry-resume.service          # run a window now
journalctl --user -u afk-data-entry-resume.service -f
```

The schedule is pure ops wiring: installing or removing it never changes any app
code or any tracked pipeline file.
