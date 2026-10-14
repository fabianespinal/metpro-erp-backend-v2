-- ============================================================
-- ROLLBACK: restore login and SELECT for supabase_read_only_user and supabase_etl_admin
-- Pairs with: 2026-10-14_retire_readonly_etl_roles.sql
-- Status:   Reversal file. NOT run. Drafted for review.
-- Restores: login for both roles, and SELECT on all tables in schema public.
--           Passwords are not changed by either file.
-- Limit:    Only SELECT on existing public tables is restored. Any other privilege
--           recorded in the pre-apply snapshot must be restored from that snapshot,
--           not from this file.
-- ============================================================

BEGIN;

ALTER ROLE supabase_read_only_user LOGIN;
ALTER ROLE supabase_etl_admin LOGIN;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO supabase_read_only_user, supabase_etl_admin;

COMMIT;
