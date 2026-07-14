#!/usr/bin/env bash
# deploy/bin/restore-drill.sh — Slice 15 §5: quarterly restore + pgcrypto verify
# =============================================================================
# Run quarterly (calendar reminder in RUNBOOK §5), by hand:
#     sudo deploy/bin/restore-drill.sh /mnt/backup/renova/db-<TS>.dump.gpg
#
# A backup you have never restored is not a backup. This proves, end to end, that:
#   1. the encrypted Postgres dump DECRYPTS with the escrowed key,
#   2. it RESTORES into a fresh scratch database, and
#   3. pgcrypto in that restored DB can encrypt+decrypt (the acceptance criterion
#      "quarterly restore drill verifies pgcrypto decryption end-to-end").
#
# It restores into a THROWAWAY database and drops it — production is never touched.
# =============================================================================
set -euo pipefail

CIPHERTEXT="${1:-}"
BACKUP_KEYFILE="${RENOVA_BACKUP_KEYFILE:-/mnt/keys/renova-backup.key}"
DRILL_DB="renova_restore_drill_$(date -u +%Y%m%dT%H%M%SZ)"
PG_SUPERUSER="${RENOVA_PG_SUPERUSER:-postgres}"   # OS user for peer-auth admin ops

# The DB admin ops (createdb/pg_restore/psql/dropdb) need superuser access. This
# script runs as root (sudo), and root peer-auths as OS user "root", which has no
# Postgres role — so route every admin call through the postgres OS user, exactly
# as safe-migrate.sh does. `psql -U postgres` connects that role over the socket.
pg() { sudo -u "$PG_SUPERUSER" "$@"; }

[[ -n "$CIPHERTEXT" ]] || { echo "usage: $0 <db-*.dump.gpg>" >&2; exit 1; }
[[ -r "$CIPHERTEXT" ]]     || { echo "cannot read $CIPHERTEXT" >&2; exit 1; }
[[ -r "$BACKUP_KEYFILE" ]] || { echo "cannot read key $BACKUP_KEYFILE" >&2; exit 1; }

WORK="$(mktemp -d)"
cleanup() { pg dropdb --if-exists "$DRILL_DB" 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT

echo "==> [1/3] decrypting dump with escrowed key"
gpg --batch --quiet --passphrase-file "$BACKUP_KEYFILE" \
    --decrypt --output "${WORK}/db.dump" "$CIPHERTEXT"
echo "    decrypted $(du -h "${WORK}/db.dump" | cut -f1)"

echo "==> [2/3] restoring into throwaway DB ${DRILL_DB}"
pg createdb "$DRILL_DB"
# Feed the dump on stdin: the root shell opens the 0700 root-owned file and sudo
# passes the fd to postgres, so the decrypted PHI never needs loosened perms.
pg pg_restore --no-owner --dbname="$DRILL_DB" < "${WORK}/db.dump"
ROWS="$(pg psql -tAqd "$DRILL_DB" -c "SELECT count(*) FROM registry_recipient;" 2>/dev/null || echo '?')"
echo "    restored — registry_recipient row count: ${ROWS}"

echo "==> [3/3] verifying pgcrypto decrypts in the restored DB"
OUT="$(pg psql -tAqd "$DRILL_DB" -c \
    "SELECT pgp_sym_decrypt(pgp_sym_encrypt('drill','k'),'k');" 2>/dev/null || true)"
if [[ "$(echo "$OUT" | tr -d '[:space:]')" != "drill" ]]; then
    echo "DRILL FAILED: pgcrypto did not round-trip in the restored DB (got '${OUT}')" >&2
    echo "  -> is pgcrypto (deploy/sql/01-pgcrypto.sql) part of the dump? investigate before trusting backups." >&2
    exit 1
fi

echo "==> RESTORE DRILL PASSED — decrypt+restore+pgcrypto all verified. Log the date in RUNBOOK §5."
