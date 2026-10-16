-- 2026-10-16: pin search_path on trigger functions (Supabase advisor 0011, Set 8).
-- NOT APPLIED. Requires explicit approval to run on production.
-- Rollback: 2026-10-16_function_search_path.rollback.sql
-- Both are zero-argument trigger functions used by BEFORE UPDATE triggers on
-- clients (update_timestamp) and projects (update_updated_at_column).
BEGIN;
ALTER FUNCTION public.update_updated_at_column() SET search_path = public, pg_temp;
ALTER FUNCTION public.update_timestamp() SET search_path = public, pg_temp;
COMMIT;
