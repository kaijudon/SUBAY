#!/usr/bin/env bash
# Remove the daily AFK data-entry resume schedule (T4 / #15). Disables and
# deletes the systemd user units. Touches no app code - the schedule is pure ops
# wiring, so unwinding it leaves the repo unchanged.
set -euo pipefail

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

systemctl --user disable --now afk-data-entry-resume.timer 2>/dev/null || true
rm -f "$UNIT_DIR/afk-data-entry-resume.timer" "$UNIT_DIR/afk-data-entry-resume.service"
systemctl --user daemon-reload

echo "Removed the AFK data-entry schedule (no app code touched)."
