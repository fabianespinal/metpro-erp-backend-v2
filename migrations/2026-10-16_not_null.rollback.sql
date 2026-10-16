BEGIN;
ALTER TABLE public.quotes ALTER COLUMN client_id DROP NOT NULL;
ALTER TABLE public.invoice_items ALTER COLUMN invoice_id DROP NOT NULL;
ALTER TABLE public.invoice_payments ALTER COLUMN invoice_id DROP NOT NULL;
ALTER TABLE public.users ALTER COLUMN role DROP NOT NULL;
ALTER TABLE public.users ALTER COLUMN role DROP DEFAULT;
ALTER TABLE public.users ALTER COLUMN password_hash DROP NOT NULL;
ALTER TABLE public.users ALTER COLUMN username DROP NOT NULL;
COMMIT;
