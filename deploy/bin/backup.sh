#!/usr/bin/env bash
# deploy/bin/backup.sh — Slice 15 §5: three-part, encrypted, off-machine backup
# =============================================================================
# Run nightly via systemd timer (deploy/systemd/subay-backup.timer), or by hand:
#     sudo deploy/bin/backup.sh
#
# Acceptance (issue 15): "three-part backup (Postgres + encrypted MEDIA_ROOT +
# secrets/pgcrypto key), the key escrowed on a separate custody path, and a
# quarterly restore drill verifies pgcrypto decryption."
#
# The three parts, all encrypted at rest so they are safe OFF the LUKS box:
#   1. Postgres dump  (pg_dump custom format)
#   2. MEDIA_ROOT     (genotyping raw files, content-addressed) as a tar
#   3. Secrets        (/etc/subay/subay.env, incl. keys) as a tar
#
# Encryption: ASYMMETRIC (public-key) gpg to a named recipient. The box holds ONLY
# the recipient's PUBLIC key, so it can write backups but can NEVER decrypt them —
# a compromised or stolen running box cannot read its own past backups. The private
# key that decrypts is escrowed OFF the box (sealed custody, RUNBOOK §8) and is only
# imported on the drill/recovery machine (deploy/bin/restore-drill.sh). This is a
# stronger custody boundary than a symmetric passphrase the box must keep on hand.
# Set SUBAY_BACKUP_GPG_RECIPIENT to the key id / fingerprint / uid to encrypt to.
#
# NO PHI is ever written to logs — only file names, sizes, and success/fail.
# =============================================================================
set -euo pipefail

# ---- operator settings (override via the systemd unit's Environment=) --------
BACKUP_DEST="${SUBAY_BACKUP_DEST:-/mnt/backup/subay}"        # off-machine target (Drive 1)
GPG_RECIPIENT="${SUBAY_BACKUP_GPG_RECIPIENT:-}"               # public key id/fpr/uid to encrypt to
GNUPGHOME="${SUBAY_BACKUP_GNUPGHOME:-}"                       # optional: dedicated keyring holding only the public key
MEDIA_ROOT="${MEDIA_ROOT:-/opt/subay/media}"
ENV_FILE="${SUBAY_ENV_FILE:-/etc/subay/subay.env}"
RETAIN_DAYS="${SUBAY_BACKUP_RETAIN_DAYS:-30}"
STAMPFILE="${SUBAY_BACKUP_STAMP:-/var/lib/subay/last-backup.stamp}"  # healthcheck reads this
# -----------------------------------------------------------------------------

TS="$(date -u +%Y%m%dT%H%M%SZ)"
log() { echo "[$(date -u +%H:%M:%SZ)] $*"; }
fail() { echo "BACKUP FAILED: $*" >&2; exit 1; }

[[ -n "${DATABASE_URL:-}" ]]  || fail "DATABASE_URL not set (load the systemd env file)"
[[ -n "$GPG_RECIPIENT" ]]     || fail "SUBAY_BACKUP_GPG_RECIPIENT not set (public key to encrypt to)"
# Optional dedicated keyring (holds ONLY the public key — the box can't decrypt).
[[ -n "$GNUPGHOME" ]] && export GNUPGHOME
# Fail loudly now if the public key isn't in the keyring, rather than mid-backup.
gpg --batch --list-keys "$GPG_RECIPIENT" >/dev/null 2>&1 \
    || fail "recipient public key '$GPG_RECIPIENT' not found in the gpg keyring — import it first"
mkdir -p "$BACKUP_DEST" "$(dirname "$STAMPFILE")"

# gpg PUBLIC-KEY encrypt to the recipient. The box has no private key, so it cannot
# decrypt what it just wrote. --trust-model always: we chose this recipient explicitly
# in config, so skip the interactive ownertrust prompt (batch mode would otherwise fail).
encrypt() {  # encrypt <plaintext-file> -> <plaintext-file>.gpg, then removes plaintext
    local src="$1"
    gpg --batch --yes --quiet \
        --trust-model always \
        --encrypt --recipient "$GPG_RECIPIENT" \
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

log "3/3 secrets archive (env + pgcrypto key material)"
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
