-- ============================================================
-- Revoke anon and authenticated access to schema public
-- Target:   Supabase PostgreSQL (public schema)
-- Status:   NOT APPLIED. Drafted for review. Do not run without explicit approval.
-- Scope:    Roles anon, authenticated. service_role is NOT changed.
--           Existing objects in public: tables, sequences, functions, schema USAGE.
--           Default privileges for objects created by postgres only.
--           Default privileges for supabase_admin are NOT changed: the postgres
--           role is not permitted to alter them (dry run 2026-10-14: permission denied).
-- Reason:   Backend connects as postgres (table owner, rolbypassrls = t).
--           Frontend has no direct Supabase access (no client, no keys).
--           Realtime publication supabase_realtime has 0 tables.
--           Storage bucket pdfs is private with 0 objects.
--           auth.users has 0 rows. No feature in use depends on these grants.
-- Residual: Objects created by supabase_admin in public would still grant to
--           anon and authenticated. Pre-apply check required: no such objects.
-- Safety:   Single transaction. Guard aborts if roles are missing.
--           Rollback: 2026-10-14_revoke_anon_authenticated.rollback.sql
--
-- Pre-apply check (read-only). Expect anon REST GET on clients to return
-- HTTP 200 with [] (publishable key, RLS denies rows, no policies).
-- Pre-apply check (read-only). Expect 0 rows:
--   select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
--   join pg_roles r on r.oid = c.relowner
--   where n.nspname = 'public' and r.rolname = 'supabase_admin';
--
-- Post-apply checks (read-only). Expect:
--   select grantee, table_name, privilege_type
--   from information_schema.role_table_grants
--   where table_schema = 'public' and grantee in ('anon','authenticated');
--   -> 0 rows
--   select has_schema_privilege('anon','public','USAGE'),
--          has_schema_privilege('authenticated','public','USAGE');
--   -> false, false
--   anon REST GET on clients -> HTTP 401 or 403 (permission denied)
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

-- Future objects created by postgres.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON FUNCTIONS FROM anon, authenticated;

COMMIT;
