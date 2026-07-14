-- SUBAY — audit integrity: restrict Postgres superuser (Slice 15, AC7).
--
-- WHY: django-simple-history records every change, but history is only tamper-EVIDENT
-- if no casual account can rewrite it. Postgres superuser can bypass row security and
-- edit history tables directly, so superuser is restricted to ONE human: the Data
-- Manager. The app's own role (`subay`) is a least-privilege login, NOT a superuser.
--
-- Run once on the real box, connected as the bootstrap superuser (HITL checkpoint).

-- 1. The application role: can read/write app tables, CANNOT create roles, CANNOT
--    bypass RLS, CANNOT touch other databases. gunicorn connects as this role.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'subay') THEN
    CREATE ROLE subay LOGIN PASSWORD NULL;   -- password set out-of-band, never here
  END IF;
END$$;

ALTER ROLE subay NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS;
GRANT CONNECT ON DATABASE subay TO subay;
GRANT USAGE ON SCHEMA public TO subay;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO subay;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO subay;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO subay;

-- 2. Confirm superuser membership is exactly one named human (the Data Manager).
--    Review the output; any unexpected superuser is a finding to remediate.
--    SELECT rolname FROM pg_roles WHERE rolsuper;

-- NTP: enforced at the OS layer, not here. The clock must be trustworthy for audit
-- timestamps to mean anything — see deploy/RUNBOOK.md §7 (chrony, single upstream,
-- makestep disabled in steady state so history timestamps never jump backwards).
