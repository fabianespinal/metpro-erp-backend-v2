-- Rollback for 2026-10-16_users_unique_and_id_default.sql
BEGIN;
DROP INDEX IF EXISTS public.users_email_lower_key;
DROP INDEX IF EXISTS public.users_username_lower_key;
ALTER TABLE public.users ALTER COLUMN id DROP DEFAULT;
COMMIT;
