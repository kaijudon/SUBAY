-- deploy/sql/02-restrict-superuser.sql — Slice 15 §7: least-privilege DB roles
-- =============================================================================
-- Run once, as the postgres superuser, against the renova database:
--     sudo -u postgres psql -d renova -f deploy/sql/02-restrict-superuser.sql
--
-- WHY: audit integrity depends on the application NOT running as a superuser.
-- django-simple-history writes an append-only change log (the audit trail), but a
-- superuser DB connection could silently rewrite or truncate history rows,
-- defeating tamper-evidence. Acceptance criterion (issue 15): "Postgres superuser
-- restricted to the Data Manager." So:
--   * the app login role `renova` gets exactly the privileges it needs — no more;
--   * superuser stays with the built-in `postgres` account, which only the Data
--     Manager can reach (local peer auth at the console), never the app.
--
-- This assumes the app role `renova` and database `renova` already exist (created
-- in LAPTOP-DEPLOY Phase 3.2). It is idempotent — safe to re-run.
-- =============================================================================

\set ON_ERROR_STOP on

-- 1. The app role must NOT be a superuser and must NOT create roles/databases.
--    (Phase 3.2 creates it with LOGIN only, but re-assert in case it drifted.)
ALTER ROLE renova NOSUPERUSER NOCREATEDB NOCREATEROLE;

-- 2. Grant only what the app needs on the existing schema objects.
GRANT CONNECT ON DATABASE renova TO renova;
GRANT USAGE ON SCHEMA public TO renova;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO renova;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO renova;

-- 3. Same grants for tables/sequences created by FUTURE migrations, so a new
--    slice's tables don't silently lose app access. Applies to objects created
--    by the postgres owner from here on.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO renova;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO renova;

-- 4. Deliberately NOT granted: TRUNCATE, and DROP/ALTER on tables. The app can
--    read and write rows but cannot destroy a table or reset a sequence — narrowing
--    the blast radius of a compromised app connection against the history tables.
--
-- Note on DELETE: django-simple-history keeps its record in SEPARATE *_history
-- tables that the ORM only ever INSERTs into. Revoking DELETE on the live tables
-- would break legitimate admin deletes, so DELETE stays; the tamper-evidence comes
-- from history rows the app never updates or deletes in normal operation, plus the
-- periodic immutable off-site history export (see deploy/RUNBOOK.md §7).

-- Verify: the app role is not a superuser.
--     sudo -u postgres psql -d renova -c "\du renova"
-- expect the "Attributes" column to be empty (no "Superuser", no "Create role").
