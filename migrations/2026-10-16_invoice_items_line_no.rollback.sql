BEGIN;
DROP INDEX IF EXISTS public.idx_invoice_items_invoice_line;
ALTER TABLE public.invoice_items DROP COLUMN IF EXISTS line_no;
COMMIT;
