-- ============================================================
-- ROLLBACK: restore login and predefined role membership for
--           supabase_read_only_user and supabase_etl_admin
-- Pairs with: 2026-10-14_retire_readonly_etl_roles.sql
-- Status:   Reversal file. NOT run. Drafted for review.
-- Restores: login for both roles, membership in pg_read_all_data and pg_monitor.
--           Passwords are not changed by either file.
-- Source:   Membership restored to the state recorded in the 2026-10-14 audit
--           (both roles in pg_read_all_data and pg_monitor).
-- ============================================================

BEGIN;

ALTER ROLE supabase_read_only_user LOGIN;
ALTER ROLE supabase_etl_admin LOGIN;

GRANT pg_read_all_data TO supabase_read_only_user, supabase_etl_admin;
GRANT pg_monitor TO supabase_read_only_user, supabase_etl_admin;

COMMIT;
