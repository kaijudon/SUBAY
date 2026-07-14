#!/usr/bin/env bash
# SUBAY — push-on-failure monitoring (Slice 15, AC6).
# Run from a frequent systemd timer (e.g. every 15 min). As the subay operator.
#
# Watches: last-backup age, disk %, app health, SSH anomalies. PUSHES only on a
# problem (quiet when healthy). Pairs with a DEAD-MAN'S SWITCH: this script also
# "checks in" on every healthy run; if the check-ins STOP, an external watcher alerts
# (because a box that has gone silent can't send its own failure alert). No PHI ever.
set -euo pipefail

NOTIFY="${NOTIFY:-/opt/subay/deploy/bin/notify-operator.sh}"
DATA_DEST="${DATA_DEST:-/var/backups/subay/data}"
DISK_PATH="${DISK_PATH:-/}"
DISK_MAX_PCT="${DISK_MAX_PCT:-85}"
BACKUP_MAX_AGE_H="${BACKUP_MAX_AGE_H:-26}"   # daily backup + 2h grace
DEADMAN_URL="${SUBAY_DEADMAN_URL:-}"        # external heartbeat endpoint (push on OK)

problems=0
alert() { "$NOTIFY" "$1" "$2"; problems=$((problems+1)); }

# 1. Last-backup age.
if [ -f "${DATA_DEST}/.last_backup_epoch" ]; then
  age_h=$(( ( $(date -u +%s) - $(cat "${DATA_DEST}/.last_backup_epoch") ) / 3600 ))
  [ "$age_h" -gt "$BACKUP_MAX_AGE_H" ] && \
    alert "backup-stale" "last backup is ${age_h}h old (>${BACKUP_MAX_AGE_H}h)"
else
  alert "backup-missing" "no backup completion marker found"
fi

# 2. Disk %.
pct="$(df --output=pcent "$DISK_PATH" | tail -1 | tr -dc '0-9')"
[ "${pct:-100}" -ge "$DISK_MAX_PCT" ] && \
  alert "disk-full" "${DISK_PATH} at ${pct}% (>=${DISK_MAX_PCT}%)"

# 3. App health — gunicorn socket answers and the service is active.
systemctl is-active --quiet subay || alert "app-down" "subay.service is not active"

# 4. SSH anomalies — recent failed auths (count only, no usernames/IPs => PHI-free op data).
fails="$(journalctl -u ssh --since '-1h' 2>/dev/null | grep -c 'Failed password\|Invalid user' || true)"
[ "${fails:-0}" -gt 20 ] && alert "ssh-anomaly" "${fails} failed SSH auths in last hour"

# Dead-man's switch: only ping the external heartbeat when everything is HEALTHY.
# If pings stop arriving, the external watcher raises the alarm this box can't send.
if [ "$problems" -eq 0 ] && [ -n "$DEADMAN_URL" ]; then
  curl --fail --silent --max-time 10 "$DEADMAN_URL" >/dev/null || true
fi

exit 0
