-- ============================================================
-- Revoke anon and authenticated access to schema public
-- Target:   Supabase PostgreSQL (public schema)
-- Status:   NOT APPLIED. Drafted for review. Do not run without explicit approval.
-- Scope:    Roles anon, authenticated. service_role is NOT changed.
-- Reason:   Backend connects as postgres (table owner, rolbypassrls = t).
--           Frontend has no direct Supabase access (no client, no keys).
--           Realtime publication supabase_realtime has 0 tables.
--           Storage bucket pdfs is private with 0 objects.
--           auth.users has 0 rows. No feature in use depends on these grants.
-- Safety:   Single transaction. Guard aborts if roles are missing.
--           Rollback: 2026-10-14_revoke_anon_authenticated.rollback.sql
--
-- Pre-apply check (read-only). Expect anon REST GET on a public table
-- to return HTTP 200 with [] today (RLS denies rows, no policies).
--
-- Post-apply checks (read-only). Expect:
--   select grantee, table_name, privilege_type
--   from information_schema.role_table_grants
--   where table_schema = 'public' and grantee in ('anon','authenticated');
--   -> 0 rows
--   select has_schema_privilege('anon','public','USAGE'),
--          has_schema_privilege('authenticated','public','USAGE');
--   -> false, false
--   anon REST GET on a public table -> HTTP 401 or 403 (permission denied)
-- ============================================================

BEGIN;

-- Guard: both roles must exist before any change.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        RAISE EXCEPTION 'Guard failed: anon or authenticated role missing. Aborting.';
    END IF;
END $$;

-- Existing objects in public.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated;
REVOKE USAGE ON SCHEMA public FROM anon, authenticated;

-- Future objects created by the owner roles.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON FUNCTIONS FROM anon, authenticated;

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public
    REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public
    REVOKE ALL ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public
    REVOKE ALL ON FUNCTIONS FROM anon, authenticated;

COMMIT;
