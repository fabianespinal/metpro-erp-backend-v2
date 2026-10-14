-- ============================================================
-- ROLLBACK: restore anon and authenticated grants on schema public
-- Pairs with: 2026-10-14_revoke_anon_authenticated.sql
-- Status:   Reversal file. NOT run. Drafted for review.
-- Restores: the Supabase default grants captured in the 2026-10-13
--           production schema-only dump (ALL on tables, sequences,
--           functions; USAGE on schema public) for anon and authenticated.
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

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public
    GRANT ALL ON TABLES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public
    GRANT ALL ON SEQUENCES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public
    GRANT ALL ON FUNCTIONS TO anon, authenticated;

COMMIT;
