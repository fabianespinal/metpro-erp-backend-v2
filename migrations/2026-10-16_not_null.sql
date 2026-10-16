-- 2026-10-16: NOT NULL fixes (Set 6).
-- NOT APPLIED. Requires explicit approval to run on production.
-- Rollback: 2026-10-16_not_null.rollback.sql
--
--   users.username, users.password_hash, users.role  NOT NULL (role default 'user')
--   invoice_payments.invoice_id                       NOT NULL
--   invoice_items.invoice_id                          NOT NULL
--   quotes.client_id                                  NOT NULL
-- (users.email stays nullable; the app requires it on create.)
--
-- Pre-check (read-only), each must return 0:
--   SELECT count(*) FROM users WHERE username IS NULL OR password_hash IS NULL OR role IS NULL;
--   SELECT count(*) FROM invoice_payments WHERE invoice_id IS NULL;
--   SELECT count(*) FROM invoice_items WHERE invoice_id IS NULL;
--   SELECT count(*) FROM quotes WHERE client_id IS NULL;

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.users WHERE username IS NULL OR password_hash IS NULL OR role IS NULL) THEN
        RAISE EXCEPTION 'users rows with NULL username, password_hash or role';
    END IF;
    IF EXISTS (SELECT 1 FROM public.invoice_payments WHERE invoice_id IS NULL) THEN
        RAISE EXCEPTION 'invoice_payments rows with NULL invoice_id';
    END IF;
    IF EXISTS (SELECT 1 FROM public.invoice_items WHERE invoice_id IS NULL) THEN
        RAISE EXCEPTION 'invoice_items rows with NULL invoice_id';
    END IF;
    IF EXISTS (SELECT 1 FROM public.quotes WHERE client_id IS NULL) THEN
        RAISE EXCEPTION 'quotes rows with NULL client_id';
    END IF;
END $$;

ALTER TABLE public.users ALTER COLUMN username SET NOT NULL;
ALTER TABLE public.users ALTER COLUMN password_hash SET NOT NULL;
ALTER TABLE public.users ALTER COLUMN role SET DEFAULT 'user';
ALTER TABLE public.users ALTER COLUMN role SET NOT NULL;
ALTER TABLE public.invoice_payments ALTER COLUMN invoice_id SET NOT NULL;
ALTER TABLE public.invoice_items ALTER COLUMN invoice_id SET NOT NULL;
ALTER TABLE public.quotes ALTER COLUMN client_id SET NOT NULL;

COMMIT;
