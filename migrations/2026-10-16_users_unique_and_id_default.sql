-- 2026-10-16: users.id default + case-insensitive unique username and email.
-- NOT APPLIED. Requires explicit approval to run on production.
-- Rollback: migrations/2026-10-16_users_unique_and_id_default.rollback.sql
--
-- Why:
--   U7: users.id is uuid NOT NULL with no default. The app now generates the UUID;
--       this default is a backstop for any other insert path.
--   U5: no uniqueness on username or email. The app checks are race-prone.
--
-- Pre-check (run first, read-only). Each must return 0 rows or the migration aborts:
--   SELECT lower(username), count(*) FROM public.users GROUP BY 1 HAVING count(*) > 1;
--   SELECT lower(email), count(*) FROM public.users WHERE email IS NOT NULL GROUP BY 1 HAVING count(*) > 1;
-- Production on 2026-10-16: 1 user, so no duplicates expected.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.users GROUP BY lower(username) HAVING count(*) > 1) THEN
        RAISE EXCEPTION 'Duplicate usernames (case-insensitive) exist; resolve before applying';
    END IF;
    IF EXISTS (SELECT 1 FROM public.users WHERE email IS NOT NULL GROUP BY lower(email) HAVING count(*) > 1) THEN
        RAISE EXCEPTION 'Duplicate emails (case-insensitive) exist; resolve before applying';
    END IF;
END $$;

ALTER TABLE public.users ALTER COLUMN id SET DEFAULT gen_random_uuid();

CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower_key ON public.users (lower(username));
CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_key ON public.users (lower(email));

COMMIT;
