#!/usr/bin/env bash
# RENOVA — three-part backup (Slice 15, AC5).
# Run from a systemd timer (see RUNBOOK §5). As the renova operator.
#
# Three parts, because restoring needs ALL THREE to be useful:
#   1. Postgres dump          (the data)
#   2. encrypted MEDIA_ROOT   (the .ab1 / report files referenced by the data)
#   3. secrets + pgcrypto key (without which an encrypted dump is unreadable)
#
# Part 3 is written to a SEPARATE custody path (KEY_DEST) from parts 1-2 (DATA_DEST):
# co-locating the key with the ciphertext would defeat pgcrypto. The key is escrowed,
# not just copied — see RUNBOOK §5/§8.
set -euo pipefail

: "${DATABASE_URL:?set via /etc/renova/renova.env}"
: "${BACKUP_GPG_RECIPIENT:?GPG key id/email that encrypts the media + secrets archives}"
APP_DIR="${APP_DIR:-/opt/renova}"
MEDIA_ROOT="${MEDIA_ROOT:-/opt/renova/media}"
SECRETS_FILE="${SECRETS_FILE:-/etc/renova/renova.env}"
DATA_DEST="${DATA_DEST:-/var/backups/renova/data}"      # Drive 1 / primary
KEY_DEST="${KEY_DEST:-/mnt/keycustody/renova}"          # separate custody path
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DB_NAME="$(printf '%s' "$DATABASE_URL" | sed -E 's#.*/([^/?]+).*#\1#')"

install -d -m 700 "$DATA_DEST" "$KEY_DEST"

# 1. Postgres dump (custom format = compressed + selective restore).
pg_dump --format=custom --dbname="$DATABASE_URL" \
        --file="${DATA_DEST}/${DB_NAME}_${STAMP}.dump"

# 2. MEDIA_ROOT, encrypted to the backup GPG recipient (asymmetric: the box can write
#    backups without holding the decryption key).
tar -C "$MEDIA_ROOT" -czf - . \
  | gpg --batch --yes --encrypt --recipient "$BACKUP_GPG_RECIPIENT" \
        --output "${DATA_DEST}/media_${STAMP}.tar.gz.gpg"

# 3. Secrets + pgcrypto key archive -> SEPARATE custody path, also GPG-encrypted.
tar -C "$(dirname "$SECRETS_FILE")" -czf - "$(basename "$SECRETS_FILE")" \
  | gpg --batch --yes --encrypt --recipient "$BACKUP_GPG_RECIPIENT" \
        --output "${KEY_DEST}/secrets_${STAMP}.tar.gz.gpg"

# Record completion for the monitor's last-backup-age check (AC6).
date -u +%s > "${DATA_DEST}/.last_backup_epoch"
echo ">> backup ${STAMP}: data+media -> ${DATA_DEST}, secrets/key -> ${KEY_DEST}"

# Retention: keep 30 daily dumps; off-site copies (Drive 2) handled in RUNBOOK §5.
find "$DATA_DEST" -name '*.dump' -mtime +30 -delete
