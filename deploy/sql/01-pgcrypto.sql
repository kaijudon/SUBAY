-- deploy/sql/01-pgcrypto.sql — Slice 15 §1: pgcrypto as defense-in-depth
-- =============================================================================
-- Run once, as the postgres superuser, against the renova database:
--     sudo -u postgres psql -d renova -f deploy/sql/01-pgcrypto.sql
--
-- WHAT THIS DOES AND WHY (read before running)
-- --------------------------------------------------------------------------
-- The re-identifying data RENOVA stores is NOT names/MRNs/addresses — the model
-- forbids those (Recipient.subject_id: "Never a name/MRN/address"). The identity
-- risk is the CALENDAR-DATE ANCHOR: Recipient.date_of_birth and Recipient.kt_date
-- (transplant = day 0). With kt_date, every de-identified day-offset in an export
-- reverses back to a real calendar date. That anchor is the crown jewel.
--
-- Layered protection for that anchor:
--   1. LUKS full-disk encryption (Phase 1) — protects a powered-off / stolen box.
--   2. pgcrypto (this file) — protects the OFF-MACHINE Postgres backup, which
--      leaves the LUKS boundary the moment it is copied to Drive 2 custody. This
--      is exactly the scope the slice sets: "pgcrypto ... as defense-in-depth
--      over off-machine backups" (issue 15).
--
-- Slice 15 delivers pgcrypto at the BACKUP layer (deploy/bin/backup.sh encrypts
-- the dump with the escrowed backup key; deploy/bin/restore-drill.sh verifies the
-- decryption end-to-end). This file installs the extension that makes that
-- verification possible and records the forward path for column-level encryption.
--
-- COLUMN-LEVEL ENCRYPTION IS DEFERRED, DELIBERATELY. The app (slices 02–14) was
-- built with native `date` columns; encrypting them to bytea requires app-layer
-- encrypt/decrypt and would break the ORM and the de-id export's offset math. Per
-- DEC-020's precedent ("at-rest encryption is an ops/mount concern; no crypto
-- dependency in app code"), the load-bearing at-rest control is LUKS + encrypted
-- backups, not per-column ciphertext. Column-level pgcrypto is left as a flagged,
-- reversible forward step — see docs/decisions/DECISIONS.md (DEC-024).
-- =============================================================================

\set ON_ERROR_STOP on

-- 1. The extension. Idempotent; safe to re-run.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 2. Smoke test — proves symmetric encrypt/decrypt round-trips in THIS database,
--    so the quarterly restore drill (deploy/bin/restore-drill.sh) has a known-good
--    baseline. Uses a throwaway literal key; no real key or PHI touches the DB.
DO $$
DECLARE
    ct  bytea;
    pt  text;
BEGIN
    ct := pgp_sym_encrypt('pgcrypto-selftest', 'throwaway-key');
    pt := pgp_sym_decrypt(ct, 'throwaway-key');
    IF pt <> 'pgcrypto-selftest' THEN
        RAISE EXCEPTION 'pgcrypto self-test FAILED (got %)', pt;
    END IF;
    RAISE NOTICE 'pgcrypto self-test OK — encrypt/decrypt round-trips.';
END
$$;

-- Verify: the extension is present.
--     sudo -u postgres psql -d renova -c "\dx pgcrypto"
-- expect one row naming the pgcrypto extension.
