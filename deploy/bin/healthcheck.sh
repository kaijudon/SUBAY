#!/usr/bin/env bash
# deploy/bin/healthcheck.sh — Slice 15 §6: push-on-failure monitoring
# =============================================================================
# Run every ~15 min via systemd timer (deploy/systemd/renova-healthcheck.timer).
#
# Acceptance (issue 15): "Push-on-failure monitoring covers last-backup age,
# disk %, app health, and SSH anomalies, has a dead-man's switch, and carries no
# PHI in any alert."
#
# Two channels:
#   * ALERT (push on failure): only fires when something is WRONG. Sends a terse,
#     PHI-FREE message via the operator-supplied RENOVA_ALERT_CMD.
#   * HEARTBEAT (dead-man's switch): pings RENOVA_HEARTBEAT_URL on every SUCCESS.
#     If the box dies entirely, the pings stop and the external heartbeat service
#     (e.g. healthchecks.io) alarms — catching the failure a push-only design can't.
#
# NO PHI RULE: this script only ever emits metric names, counts, thresholds, and
# the host name — never a subject_id, a row's contents, or a query result.
# =============================================================================
set -uo pipefail   # NOT -e: a single failed check must still let the others run

# ---- operator settings (override via the systemd unit's Environment=) --------
APP_URL="${RENOVA_APP_URL:-https://127.0.0.1/}"
STAMPFILE="${RENOVA_BACKUP_STAMP:-/var/lib/renova/last-backup.stamp}"
MAX_BACKUP_AGE_H="${RENOVA_MAX_BACKUP_AGE_H:-26}"     # nightly + slack
DISK_PATHS="${RENOVA_DISK_PATHS:-/ /var}"
DISK_WARN_PCT="${RENOVA_DISK_WARN_PCT:-85}"
ALERT_CMD="${RENOVA_ALERT_CMD:-}"                     # e.g. 'mail -s RENOVA op@example' or a curl
# Single PHI-free push chokepoint (deploy/bin/notify-operator.sh). Preferred over
# ALERT_CMD so every operator alert — monitoring, reboot-required — arrives the same
# way through one place that must stay PHI-free.
NOTIFY="${RENOVA_NOTIFY:-/opt/renova/deploy/bin/notify-operator.sh}"
HEARTBEAT_URL="${RENOVA_HEARTBEAT_URL:-}"            # dead-man's switch ping target
# -----------------------------------------------------------------------------

HOST="$(hostname -s)"
PROBLEMS=()
add() { PROBLEMS+=("$1"); }

# 1. last-backup age (reads the stamp backup.sh writes on success; no data).
if [[ -f "$STAMPFILE" ]]; then
    age_h=$(( ( $(date -u +%s) - $(cat "$STAMPFILE") ) / 3600 ))
    (( age_h > MAX_BACKUP_AGE_H )) && add "backup stale: ${age_h}h > ${MAX_BACKUP_AGE_H}h"
else
    add "backup stamp missing (${STAMPFILE}) — has backup.sh ever succeeded?"
fi

# 2. disk % on the paths that matter (Postgres + backups fill these).
for p in $DISK_PATHS; do
    if used=$(df --output=pcent "$p" 2>/dev/null | tr -dc '0-9'); then
        (( used > DISK_WARN_PCT )) && add "disk ${p} at ${used}% > ${DISK_WARN_PCT}%"
    fi
done

# 3. app health — HTTP reachability only. We never fetch a data page, so no PHI
#    can be captured. --insecure because the cert is locally-trusted (Slice 0).
# curl's -w already prints the code (000 on connection failure), so DON'T append
# a fallback echo — that would concatenate into "000000". Ignore curl's exit code.
code=$(curl -s -o /dev/null -w '%{http_code}' --insecure --max-time 10 "$APP_URL" || true)
code=${code:-000}
[[ "$code" =~ ^(200|301|302|403)$ ]] || add "app unhealthy: HTTP ${code} from ${APP_URL}"

# 4. SSH anomalies — COUNT of failed logins in the last hour (a number, not who/where).
if command -v journalctl >/dev/null 2>&1; then
    fails=$(journalctl -u ssh --since '1 hour ago' 2>/dev/null | grep -c 'Failed password' || true)
    (( fails > 20 )) && add "ssh: ${fails} failed logins in last hour"
fi

# ---- dispatch ---------------------------------------------------------------
if (( ${#PROBLEMS[@]} > 0 )); then
    SUMMARY="$(printf '%s; ' "${PROBLEMS[@]}")"
    MSG="RENOVA[${HOST}] ALERT: ${SUMMARY}"
    echo "$MSG" >&2
    # Prefer the single notify chokepoint; fall back to a raw ALERT_CMD if set.
    if [[ -x "$NOTIFY" ]]; then
        "$NOTIFY" "healthcheck" "$SUMMARY" || echo "alert dispatch failed" >&2
    elif [[ -n "$ALERT_CMD" ]]; then
        printf '%s\n' "$MSG" | eval "$ALERT_CMD" || echo "alert dispatch failed" >&2
    fi
    exit 1
fi

# All green: fire the dead-man's-switch heartbeat so an external monitor knows the
# box is alive. Silence here (box dead) is what makes that monitor alarm.
[[ -n "$HEARTBEAT_URL" ]] && curl -fsS --max-time 10 "$HEARTBEAT_URL" >/dev/null 2>&1 || true
echo "RENOVA[${HOST}] healthy"
