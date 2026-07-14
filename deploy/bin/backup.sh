#!/usr/bin/env bash
# deploy/bin/backup.sh — Slice 15 §5: three-part, encrypted, off-machine backup
# =============================================================================
# Run nightly via systemd timer (deploy/systemd/renova-backup.timer), or by hand:
#     sudo deploy/bin/backup.sh
#
# Acceptance (issue 15): "three-part backup (Postgres + encrypted MEDIA_ROOT +
# secrets/pgcrypto key), the key escrowed on a separate custody path, and a
# quarterly restore drill verifies pgcrypto decryption."
#
# The three parts, all encrypted at rest so they are safe OFF the LUKS box:
#   1. Postgres dump  (pg_dump custom format)
#   2. MEDIA_ROOT     (genotyping raw files, content-addressed) as a tar
#   3. Secrets        (/etc/renova/renova.env, incl. keys) as a tar
#
# Encryption: symmetric AES-256 via gpg, using a passphrase read from a key file
# that lives on a SEPARATE custody path from the backups themselves (you must
# never store the key next to the ciphertext it unlocks). Set BACKUP_KEYFILE to a
# path on a different volume/USB than BACKUP_DEST.
#
# NO PHI is ever written to logs — only file names, sizes, and success/fail.
# =============================================================================
set -euo pipefail

# ---- operator settings (override via the systemd unit's Environment=) --------
BACKUP_DEST="${RENOVA_BACKUP_DEST:-/mnt/backup/renova}"        # off-machine target (Drive 1)
BACKUP_KEYFILE="${RENOVA_BACKUP_KEYFILE:-/mnt/keys/renova-backup.key}"  # SEPARATE custody
MEDIA_ROOT="${MEDIA_ROOT:-/opt/renova/media}"
ENV_FILE="${RENOVA_ENV_FILE:-/etc/renova/renova.env}"
RETAIN_DAYS="${RENOVA_BACKUP_RETAIN_DAYS:-30}"
STAMPFILE="${RENOVA_BACKUP_STAMP:-/var/lib/renova/last-backup.stamp}"  # healthcheck reads this
# -----------------------------------------------------------------------------

TS="$(date -u +%Y%m%dT%H%M%SZ)"
log() { echo "[$(date -u +%H:%M:%SZ)] $*"; }
fail() { echo "BACKUP FAILED: $*" >&2; exit 1; }

[[ -n "${DATABASE_URL:-}" ]] || fail "DATABASE_URL not set (load the systemd env file)"
[[ -r "$BACKUP_KEYFILE" ]]   || fail "backup key not readable at $BACKUP_KEYFILE (separate custody path)"
mkdir -p "$BACKUP_DEST" "$(dirname "$STAMPFILE")"

# gpg symmetric encrypt from the keyfile passphrase. Never echoes the key.
encrypt() {  # encrypt <plaintext-file> -> <plaintext-file>.gpg, then removes plaintext
    local src="$1"
    gpg --batch --yes --quiet \
        --passphrase-file "$BACKUP_KEYFILE" \
        --cipher-algo AES256 --symmetric \
        --output "${src}.gpg" "$src"
    rm -f "$src"
}

STAGE="$(mktemp -d "${BACKUP_DEST}/.staging-${TS}.XXXX")"
trap 'rm -rf "$STAGE"' EXIT

log "1/3 Postgres dump"
pg_dump --format=custom --dbname="$DATABASE_URL" --file="${STAGE}/db-${TS}.dump" \
    || fail "pg_dump"
encrypt "${STAGE}/db-${TS}.dump"

log "2/3 MEDIA_ROOT archive"
if [[ -d "$MEDIA_ROOT" ]]; then
    tar -C "$(dirname "$MEDIA_ROOT")" -cf "${STAGE}/media-${TS}.tar" "$(basename "$MEDIA_ROOT")" \
        || fail "tar MEDIA_ROOT"
    encrypt "${STAGE}/media-${TS}.tar"
else
    log "    (no MEDIA_ROOT at $MEDIA_ROOT yet — skipping part 2)"
fi

log "3/3 secrets archive (env + pgcrypto/backup key material)"
tar -C "$(dirname "$ENV_FILE")" -cf "${STAGE}/secrets-${TS}.tar" "$(basename "$ENV_FILE")" \
    || fail "tar secrets"
encrypt "${STAGE}/secrets-${TS}.tar"

# Publish atomically: move the .gpg files into place, drop a manifest of sizes+sha.
( cd "$STAGE" && sha256sum ./*.gpg > "manifest-${TS}.sha256" )
mv "${STAGE}"/*.gpg "${STAGE}"/manifest-*.sha256 "$BACKUP_DEST"/

# Retention: prune ciphertext older than RETAIN_DAYS (dump/media/secrets/manifest).
find "$BACKUP_DEST" -maxdepth 1 -type f \( -name '*.gpg' -o -name 'manifest-*.sha256' \) \
    -mtime "+${RETAIN_DAYS}" -delete

# Success stamp — the healthcheck's last-backup-age signal reads this mtime.
date -u +%s > "$STAMPFILE"
log "OK — 3-part encrypted backup in ${BACKUP_DEST} (retain ${RETAIN_DAYS}d)"
log "REMINDER: copy today's *.gpg to off-site Drive 2 custody (bus-factor, RUNBOOK §8)."
