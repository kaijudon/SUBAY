#!/usr/bin/env bash
# Install the daily AFK data-entry resume schedule (T4 / #15) as a systemd USER
# timer. Substitutes the repo's absolute path into the units and enables the
# timer. Unwind at any time with uninstall-schedule.sh - no app code is touched.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"

for u in afk-data-entry-resume.service afk-data-entry-resume.timer; do
  sed "s#@REPO@#$REPO#g" "$REPO/.sandcastle/systemd/$u" > "$UNIT_DIR/$u"
done

systemctl --user daemon-reload
systemctl --user enable --now afk-data-entry-resume.timer
systemctl --user list-timers afk-data-entry-resume.timer --all || true

cat <<EOF

Installed. The timer fires daily at 21:00 UTC (05:00 PHT).
For it to run while you are logged out, enable lingering once:
    loginctl enable-linger "$USER"
Trigger a window now to test:
    systemctl --user start afk-data-entry-resume.service
Follow it:
    journalctl --user -u afk-data-entry-resume.service -f
EOF
