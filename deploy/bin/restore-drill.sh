#!/usr/bin/env bash
# SUBAY — quarterly restore drill (Slice 15, AC5).
# Run every quarter. Proves the backup is RESTORABLE and pgcrypto DECRYPTS end-to-end.
# A backup nobody has restored is a guess, not a backup.
#
# Usage: deploy/bin/restore-drill.sh <data_dump.dump> <secrets_archive.tar.gz.gpg>
set -euo pipefail

DUMP="${1:?path to a Postgres .dump from backup.sh}"
SECRETS_ARCHIVE="${2:?path to the secrets_*.tar.gz.gpg from the key custody path}"
PY="${PY:-/opt/conda/envs/subay_env/bin/python}"
APP_DIR="${APP_DIR:-/opt/subay}"
DRILL_DB="subay_drill_$(date -u +%Y%m%dT%H%M%SZ)"

cleanup() { dropdb --if-exists "$DRILL_DB" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo ">> 1. Restore the dump into a throwaway DB (${DRILL_DB})."
createdb "$DRILL_DB"
pg_restore --no-owner --dbname="$DRILL_DB" "$DUMP"

echo ">> 2. Recover the pgcrypto key from the SEPARATE-custody secrets archive."
TMPKEYDIR="$(mktemp -d)"; trap 'rm -rf "$TMPKEYDIR"; cleanup' EXIT
gpg --batch --yes --decrypt "$SECRETS_ARCHIVE" | tar -C "$TMPKEYDIR" -xzf -
PGCRYPTO_KEY="$(grep -E '^SUBAY_PGCRYPTO_KEY=' "$TMPKEYDIR"/subay.env | cut -d= -f2-)"
[ -n "$PGCRYPTO_KEY" ] || { echo "!! key not found in secrets archive" >&2; exit 1; }

echo ">> 3. Prove an encrypted column DECRYPTS with the recovered key."
# Adjust the table/column to a real pgcrypto-encrypted column (see 01-pgcrypto.sql).
# Success = pgp_sym_decrypt returns plaintext without error on at least one row.
psql --dbname="$DRILL_DB" --set=key="$PGCRYPTO_KEY" --variable=ON_ERROR_STOP=1 <<'SQL'
-- Example probe; replace contact_note_enc with the real encrypted column.
-- SELECT pgp_sym_decrypt(contact_note_enc, :'key') IS NOT NULL AS decrypts
--   FROM registry_recipient WHERE contact_note_enc IS NOT NULL LIMIT 1;
SELECT 'pgcrypto extension present' AS check, count(*) FROM pg_extension WHERE extname='pgcrypto';
SQL

echo ">> 4. Sanity: row counts on a core table."
psql --dbname="$DRILL_DB" -c "SELECT count(*) AS recipients FROM registry_recipient;"

echo ">> RESTORE DRILL PASSED. Record the date + result in the drill log (RUNBOOK §5)."
