#!/usr/bin/env bash
# SUBAY — safe migration wrapper (Slice 15, AC3).
# Usage (on the real box, as the subay operator):
#   deploy/bin/safe-migrate.sh
#
# WHY: a migration is the one routine operation that can silently destroy data. This
# wrapper makes three guarantees, in order:
#   1. ALWAYS pg_dump before touching the schema (rollback point).
#   2. Apply ADDITIVE migrations directly (safe: new tables/columns/indexes).
#   3. REHEARSE destructive / RunPython migrations on a throwaway scratch DB first,
#      and refuse to auto-apply them — a human reviews the rehearsal, then applies.
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL must be set (loaded from /etc/subay/subay.env)}"
APP_DIR="${APP_DIR:-/opt/subay}"
PY="${PY:-/opt/conda/envs/subay_env/bin/python}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/subay/premigrate}"
DB_NAME="$(printf '%s' "$DATABASE_URL" | sed -E 's#.*/([^/?]+).*#\1#')"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

cd "$APP_DIR"
install -d -m 700 "$BACKUP_DIR"

# 1. Rollback point. If this fails, we do NOT migrate.
DUMP="${BACKUP_DIR}/${DB_NAME}_${STAMP}.dump"
echo ">> pg_dump -> ${DUMP}"
pg_dump --format=custom --dbname="$DATABASE_URL" --file="$DUMP"
echo ">> backup OK ($(du -h "$DUMP" | cut -f1))"

# Detect unapplied migrations that contain RunPython / RunSQL / destructive ops.
# `makemigrations --check` first: the repo must already hold the migration files;
# this wrapper never generates schema on the production box.
if ! "$PY" manage.py makemigrations --check --dry-run >/dev/null 2>&1; then
  echo "!! Model/migration drift: unmade migrations exist in the repo." >&2
  echo "!! Generate + review them in dev and redeploy. Refusing to proceed." >&2
  exit 1
fi

PLAN="$("$PY" manage.py migrate --plan 2>/dev/null || true)"
if [ -z "$PLAN" ]; then
  echo ">> No unapplied migrations. Nothing to do."
  exit 0
fi
echo ">> Pending plan:"; echo "$PLAN"

# 2/3. Scan the pending migration FILES for risky operations.
RISKY="$("$PY" manage.py migrate --plan 2>/dev/null \
  | grep -oE '[a-z_]+\.[0-9]{4}_[a-z0-9_]+' || true)"
NEEDS_REHEARSAL=0
for mig in $RISKY; do
  app="${mig%%.*}"; name="${mig#*.}"
  f="$(find "$APP_DIR" -path "*/${app}/migrations/${name}.py" | head -1)"
  [ -n "$f" ] || continue
  if grep -qE 'RunPython|RunSQL|RemoveField|DeleteModel|AlterField.*->|DROP ' "$f"; then
    echo "!! REHEARSAL REQUIRED: $mig ($f) contains a destructive/RunPython op."
    NEEDS_REHEARSAL=1
  fi
done

if [ "$NEEDS_REHEARSAL" -eq 1 ]; then
  echo ">> Rehearsing on a scratch DB restored from the backup just taken..."
  SCRATCH="subay_scratch_${STAMP}"
  createdb "$SCRATCH"
  pg_restore --no-owner --dbname="$SCRATCH" "$DUMP"
  DATABASE_URL="postgres://subay@127.0.0.1:5432/${SCRATCH}" \
    "$PY" manage.py migrate --no-input
  echo ">> Rehearsal succeeded on ${SCRATCH}."
  echo ">> A human must review the rehearsal, then apply to production with:"
  echo "     $PY manage.py migrate --no-input"
  echo ">> Scratch DB left for inspection; drop it with: dropdb ${SCRATCH}"
  echo "!! NOT auto-applying a destructive migration. Stopping."
  exit 2
fi

# Additive-only: safe to apply directly.
echo ">> Additive migrations only — applying directly."
"$PY" manage.py migrate --no-input
echo ">> migrate complete. Pre-migration backup: ${DUMP}"
