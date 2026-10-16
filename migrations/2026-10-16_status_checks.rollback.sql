BEGIN;
ALTER TABLE public.invoices DROP CONSTRAINT IF EXISTS invoices_status_check;
ALTER TABLE public.invoices ALTER COLUMN status SET DEFAULT 'Draft';
ALTER TABLE public.quotes DROP CONSTRAINT IF EXISTS quotes_status_check;
ALTER TABLE public.quotes ALTER COLUMN status DROP NOT NULL;
COMMIT;
