-- ============================================================
-- Retire login roles supabase_read_only_user and supabase_etl_admin
-- Target:   Supabase PostgreSQL
-- Status:   NOT APPLIED. Drafted for review. Do not run without explicit approval.
-- Scope:    Revoke membership in pg_read_all_data and pg_monitor from both roles.
--           Disable login for both roles (ALTER ROLE ... NOLOGIN).
--           Passwords are NOT changed by this migration.
-- Reason:   Audit 2026-10-14: both roles inherit pg_read_all_data and pg_monitor.
--           pg_read_all_data grants SELECT on all tables in all schemas, not only
--           public. Direct ACLs on public tables show no entries for these roles,
--           so REVOKE on tables would have been a no-op.
--           Both roles are login roles with no password expiry.
--           No active sessions observed at audit time. Tool usage not confirmed.
-- Safety:   Single transaction. Guard aborts if a role is missing or if any
--           session for either role is active. ALTER ROLE does not end sessions,
--           so the guard is required.
-- Residual: If REVOKE of a predefined role membership is denied, the transaction
--           aborts and nothing changes. Dry run required before apply.
-- Rollback: 2026-10-14_retire_readonly_etl_roles.rollback.sql
--
-- Pre-apply snapshot (read-only). Record the output before apply.
--   select m.rolname as member, g.rolname as inherits_from
--   from pg_auth_members a
--   join pg_roles m on m.oid = a.member
--   join pg_roles g on g.oid = a.roleid
--   where m.rolname in ('supabase_read_only_user','supabase_etl_admin')
--   order by 1,2;
--   select rolname, rolcanlogin, rolvaliduntil from pg_roles
--   where rolname in ('supabase_read_only_user','supabase_etl_admin');
--   select usename, count(*) from pg_stat_activity
--   where usename in ('supabase_read_only_user','supabase_etl_admin') group by 1;
--   Expected: membership rows for pg_read_all_data and pg_monitor (4 rows),
--   login true for both, no active sessions.
--
-- Post-apply checks (read-only). Expect:
--   The membership query above returns 0 rows.
--   rolcanlogin false for both roles.
--   Effective read check (has_table_privilege) false on public tables for both roles.
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

REVOKE pg_read_all_data FROM supabase_read_only_user, supabase_etl_admin;
REVOKE pg_monitor FROM supabase_read_only_user, supabase_etl_admin;

ALTER ROLE supabase_read_only_user NOLOGIN;
ALTER ROLE supabase_etl_admin NOLOGIN;

COMMIT;
