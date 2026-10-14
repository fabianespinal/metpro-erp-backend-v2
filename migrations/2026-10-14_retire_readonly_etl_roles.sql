-- ============================================================
-- Retire login roles supabase_read_only_user and supabase_etl_admin
-- Target:   Supabase PostgreSQL (public schema)
-- Status:   NOT APPLIED. Drafted for review. Do not run without explicit approval.
-- Scope:    Revoke SELECT on all tables in schema public from both roles.
--           Disable login for both roles (ALTER ROLE ... NOLOGIN).
--           Passwords are NOT changed by this migration.
-- Reason:   Role audit 2026-10-14: both roles hold SELECT on all 12 public tables,
--           including users. Both are login roles with no password expiry.
--           No active sessions observed at audit time. No tool usage confirmed.
-- Safety:   Single transaction. Guard aborts if a role is missing or if any
--           session for either role is active. ALTER ROLE does not end sessions,
--           so the guard is required.
-- Residual: Only SELECT is revoked. Any other privilege these roles hold on
--           public (not checked in the audit) is not changed. Check with the
--           pre-apply snapshot below.
-- Rollback: 2026-10-14_retire_readonly_etl_roles.rollback.sql
--
-- Pre-apply snapshot (read-only). Record the output before apply.
--   select grantee, table_schema, table_name, privilege_type
--   from information_schema.role_table_grants
--   where grantee in ('supabase_read_only_user','supabase_etl_admin')
--   order by 1,2,3,4;
--   select rolname, rolcanlogin, rolvaliduntil from pg_roles
--   where rolname in ('supabase_read_only_user','supabase_etl_admin');
--   select usename, count(*) from pg_stat_activity
--   where usename in ('supabase_read_only_user','supabase_etl_admin') group by 1;
--   Expected: all privileges above are SELECT only, login true, no active sessions.
--   If the snapshot shows any other privilege, stop and report before apply.
--
-- Post-apply checks (read-only). Expect:
--   select grantee, count(*) from information_schema.role_table_grants
--   where grantee in ('supabase_read_only_user','supabase_etl_admin') group by 1;
--   -> 0 rows
--   select rolname, rolcanlogin from pg_roles
--   where rolname in ('supabase_read_only_user','supabase_etl_admin');
--   -> rolcanlogin false for both
--   Login attempt with the old password -> authentication failure
-- ============================================================

BEGIN;

-- Guard: roles must exist and have no active sessions.
DO $$
DECLARE
    active_count integer;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_read_only_user')
       OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_etl_admin') THEN
        RAISE EXCEPTION 'Guard failed: target role missing. Aborting.';
    END IF;

    SELECT count(*) INTO active_count
    FROM pg_stat_activity
    WHERE usename IN ('supabase_read_only_user', 'supabase_etl_admin');

    IF active_count <> 0 THEN
        RAISE EXCEPTION 'Guard failed: % active session(s) for retired roles. Aborting.', active_count;
    END IF;
END $$;

REVOKE SELECT ON ALL TABLES IN SCHEMA public FROM supabase_read_only_user, supabase_etl_admin;

ALTER ROLE supabase_read_only_user NOLOGIN;
ALTER ROLE supabase_etl_admin NOLOGIN;

COMMIT;
