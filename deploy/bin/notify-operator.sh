#!/usr/bin/env bash
# RENOVA — operator push channel (Slice 15, AC6). Single chokepoint for ALL alerts
# (monitoring, reboot-required) so there is one place to configure + one place that
# must stay PHI-free.
#
# Usage: notify-operator.sh <short-tag> <message>
#
# CRITICAL: messages MUST NOT contain PHI. Senders pass operational facts only
# (counts, ages, percentages, host state) — never patient data, never row contents.
set -euo pipefail

TAG="${1:?short tag}"; MSG="${2:?message}"
HOST="$(hostname -s)"
WEBHOOK_URL="${RENOVA_ALERT_WEBHOOK:-}"   # from /etc/renova/renova.env; push, not poll

PAYLOAD="[RENOVA/${HOST}] ${TAG}: ${MSG}"

if [ -n "$WEBHOOK_URL" ]; then
  # --fail so a delivery failure is itself a non-zero exit the caller/timer can catch.
  curl --fail --silent --show-error --max-time 15 \
       -H 'Content-Type: application/json' \
       -d "$(printf '{"text":%s}' "$(printf '%s' "$PAYLOAD" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')")" \
       "$WEBHOOK_URL" >/dev/null
else
  logger -t renova-alert "$PAYLOAD"   # fallback to journald if no webhook configured
fi
