-- ============================================================
-- ROLLBACK: restore anon and authenticated grants on schema public
-- Pairs with: 2026-10-14_revoke_anon_authenticated.sql
-- Status:   Reversal file. NOT run. Drafted for review.
-- Restores: grants captured in the 2026-10-13 production schema-only dump for
--           anon and authenticated: USAGE on schema public, ALL on existing
--           tables, sequences, functions, and default privileges for objects
--           created by postgres.
--           supabase_admin defaults were never changed by the forward migration,
--           so nothing is restored for them here.
--           service_role was never changed and is not touched here.
-- ============================================================

BEGIN;

GRANT USAGE ON SCHEMA public TO anon, authenticated;
GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO anon, authenticated;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT ALL ON TABLES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT ALL ON SEQUENCES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT ALL ON FUNCTIONS TO anon, authenticated;

COMMIT;
