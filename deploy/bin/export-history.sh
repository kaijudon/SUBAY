#!/usr/bin/env bash
# RENOVA — tamper-evident history export (Slice 15, AC7).
# Run weekly from a timer. Dumps django-simple-history tables to a hash-stamped,
# append-only file pushed to immutable off-site storage (Drive 2 / object-lock bucket).
#
# WHY: history lives in the same Postgres a privileged user could edit. Periodically
# exporting it OFF the box, with a content hash, makes after-the-fact tampering
# detectable: a changed past = a hash that no longer matches the prior export.
set -euo pipefail

: "${DATABASE_URL:?set via /etc/renova/renova.env}"
OUT_DIR="${HISTORY_OUT_DIR:-/var/backups/renova/history}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 700 "$OUT_DIR"
OUT="${OUT_DIR}/history_${STAMP}.sql.gz"

# Dump only the historical* tables (data-only; schema comes from the repo).
HIST_TABLES="$(psql --dbname="$DATABASE_URL" -At -c \
  "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'registry_historical%';")"

# shellcheck disable=SC2086
pg_dump --dbname="$DATABASE_URL" --data-only \
  $(for t in $HIST_TABLES; do printf ' -t %s' "$t"; done) \
  | gzip -9 > "$OUT"

# Hash stamp: chain to the previous export's hash so the sequence is verifiable.
PREV_HASH="$(cat "${OUT_DIR}/.last_hash" 2>/dev/null || echo GENESIS)"
THIS_HASH="$(sha256sum "$OUT" | cut -d' ' -f1)"
printf '%s  %s  prev=%s\n' "$STAMP" "$THIS_HASH" "$PREV_HASH" >> "${OUT_DIR}/history_chain.log"
printf '%s' "$THIS_HASH" > "${OUT_DIR}/.last_hash"

echo ">> history export ${STAMP} sha256=${THIS_HASH} (prev=${PREV_HASH})"
echo ">> Push ${OUT} + history_chain.log to the IMMUTABLE off-site bucket (object-lock)."
# rclone/aws s3 cp with object-lock retention is configured per RUNBOOK §7 — the bucket
# enforces write-once so even a compromised box cannot rewrite past exports.
