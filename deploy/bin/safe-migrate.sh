#!/usr/bin/env bash
# deploy/bin/safe-migrate.sh — Slice 15 §3: never migrate without a fresh dump
# =============================================================================
# Use this INSTEAD of `manage.py migrate` on the production box. Run as root so it
# can create the scratch DB via the postgres superuser:
#     cd /opt/renova
#     set -a; source <(sudo cat /etc/renova/renova.env); set +a
#     sudo -E deploy/bin/safe-migrate.sh
#
# Acceptance (issue 15): "pg_dump before every migrate, applies additive migrations
# directly, and rehearses RunPython/destructive migrations on a scratch DB first."
#
# Order:
#   1. pg_dump the live DB (custom format) — the rollback point.
#   2. Show the migration plan.
#   3. If any pending migration is a data migration (RunPython/RunSQL) or a
#      destructive schema op, replay the WHOLE plan on a throwaway scratch DB
#      restored from the dump. Only a clean rehearsal proceeds to prod.
#   4. Apply to prod.
#
# Privilege model: the app role is NOCREATEDB (deploy/sql/02-restrict-superuser.sql),
# so the scratch DB is created by the postgres superuser (`sudo -u postgres`) but
# OWNED BY the app role, which then restores + migrates it with its own credentials.
#
# Env: DATABASE_URL + DJANGO_SECRET_KEY loaded (systemd env file); conda env present.
# =============================================================================
set -euo pipefail

PYTHON="${RENOVA_PYTHON:-/opt/conda/envs/renova_env/bin/python}"
MANAGE="${RENOVA_DIR:-/opt/renova}/manage.py"
BACKUP_DIR="${RENOVA_MIGRATE_BACKUPS:-/var/backups/renova/pre-migrate}"
PG_SUPERUSER="${RENOVA_PG_SUPERUSER:-postgres}"   # OS user for peer-auth admin ops
TS="$(date -u +%Y%m%dT%H%M%SZ)"

[[ -n "${DATABASE_URL:-}" ]] || { echo "DATABASE_URL not set — load the env file, run with sudo -E." >&2; exit 1; }

# App DB name and role, parsed from postgres://role:pass@host:port/dbname[?...]
DB_NAME="$(printf '%s' "$DATABASE_URL"  | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')"
# The role must appear between "://" and the ":pass"/"@host". `-n ...p` only prints
# on a match, so a userless URL yields an empty DB_ROLE we can reject, rather than
# sed echoing the whole URL back (which would corrupt `createdb -O`).
DB_ROLE="$(printf '%s' "$DATABASE_URL" | sed -nE 's#^[^:]+://([^:/@]+)[:@].*#\1#p')"
if [[ -z "$DB_ROLE" ]]; then
    echo "could not parse a DB role from DATABASE_URL — the scratch rehearsal needs one." >&2
    echo "expected postgres://ROLE:pass@host/db; set RENOVA_PG_SUPERUSER/DATABASE_URL accordingly." >&2
    exit 1
fi
SCRATCH_DB="renova_scratch_${TS}"
SCRATCH_URL="$(printf '%s' "$DATABASE_URL" | sed -E "s#/${DB_NAME}(\?|$)#/${SCRATCH_DB}\1#")"

echo "==> [1/4] pg_dump ${DB_NAME} -> rollback point"
mkdir -p "$BACKUP_DIR"
DUMP="${BACKUP_DIR}/${DB_NAME}-${TS}.dump"
pg_dump --format=custom --dbname="$DATABASE_URL" --file="$DUMP"
echo "    wrote ${DUMP}"

# Drift guard: the repo must already hold every migration file. This wrapper never
# generates schema on the production box — unmade migrations mean the code and the
# committed migrations disagree, so refuse rather than silently skip a model change.
if ! "$PYTHON" "$MANAGE" makemigrations --check --dry-run >/dev/null 2>&1; then
    echo "!! model/migration drift: unmade migrations exist — generate + review them in dev, redeploy." >&2
    echo "!! refusing to migrate against a repo whose migrations don't match its models." >&2
    exit 1
fi

echo "==> [2/4] migration plan"
"$PYTHON" "$MANAGE" migrate --plan

# Detect data/destructive migrations among the UNAPPLIED ones. We inspect each
# pending migration's actual `operations` list via Django's migration loader
# rather than grepping source text — introspection is immune to how the file is
# formatted (multi-line operations, comments) and to bracket-splitting in the
# plan output. Prints the name of every migration that needs a rehearsal.
NEEDS_REHEARSAL=0
RISKY="$(RENOVA_DIR="${RENOVA_DIR:-/opt/renova}" "$PYTHON" - <<'PY'
import os, sys
# Bare `python -` has no Django context (unlike manage.py), so bootstrap settings
# before touching the ORM connection — mirrors scripts/otp_token.py.
sys.path.insert(0, os.environ.get("RENOVA_DIR", "/opt/renova"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "renova.settings")
import django
django.setup()
from django.db.migrations.loader import MigrationLoader
from django.db.migrations import operations as ops
from django.db import connection

# Ops that can lose data or run arbitrary code -> must rehearse on a scratch DB.
DESTRUCTIVE = (ops.RunPython, ops.RunSQL, ops.RemoveField, ops.DeleteModel,
               ops.RenameField, ops.RenameModel, ops.AlterModelTable)

loader = MigrationLoader(connection)
applied = set(loader.applied_migrations)
graph = loader.graph
for key in graph.nodes:                       # (app_label, migration_name)
    if key in applied:
        continue
    migration = loader.get_migration(*key)
    for op in migration.operations:
        # A NOT NULL tightening on an existing column can fail/lose rows too.
        tightens_null = isinstance(op, ops.AlterField) and getattr(
            op.field, "null", True) is False
        if isinstance(op, DESTRUCTIVE) or tightens_null:
            print(f"{key[0]}.{key[1]}")
            break
PY
)"
if [[ -n "$RISKY" ]]; then
    NEEDS_REHEARSAL=1
    while IFS= read -r mig; do
        [[ -n "$mig" ]] && echo "    data/destructive migration detected: ${mig}"
    done <<< "$RISKY"
fi

if [[ "$NEEDS_REHEARSAL" -eq 1 ]]; then
    echo "==> [3/4] rehearsing on scratch DB ${SCRATCH_DB} (owned by ${DB_ROLE}, restored from the dump)"
    # postgres creates the empty DB owned by the app role (app role is NOCREATEDB).
    sudo -u "$PG_SUPERUSER" createdb -O "$DB_ROLE" "$SCRATCH_DB"
    # shellcheck disable=SC2064
    trap "sudo -u '$PG_SUPERUSER' dropdb --if-exists '$SCRATCH_DB'" EXIT
    # Restore + migrate AS THE APP ROLE (its own credentials), so ownership matches prod.
    pg_restore --no-owner --dbname="$SCRATCH_URL" "$DUMP"
    DATABASE_URL="$SCRATCH_URL" "$PYTHON" "$MANAGE" migrate --no-input
    echo "    rehearsal succeeded — the plan applies cleanly on real data."
    sudo -u "$PG_SUPERUSER" dropdb --if-exists "$SCRATCH_DB"
    trap - EXIT
else
    echo "==> [3/4] additive-only plan — no scratch rehearsal needed"
fi

echo "==> [4/4] applying migrations to ${DB_NAME}"
"$PYTHON" "$MANAGE" migrate --no-input
echo "==> done. Rollback if needed:  pg_restore --clean --no-owner --dbname=\"\$DATABASE_URL\" ${DUMP}"
