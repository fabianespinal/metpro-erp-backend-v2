BEGIN;
ALTER TABLE public.invoice_items DROP CONSTRAINT IF EXISTS invoice_items_invoice_id_fkey;
ALTER TABLE public.invoice_items ADD CONSTRAINT invoice_items_invoice_id_fkey
    FOREIGN KEY (invoice_id) REFERENCES public.invoices(id);
ALTER TABLE public.invoice_items DROP CONSTRAINT IF EXISTS invoice_items_product_id_fkey;
ALTER TABLE public.quote_items DROP CONSTRAINT IF EXISTS quote_items_product_id_fkey;
ALTER TABLE public.quote_items DROP CONSTRAINT IF EXISTS quote_items_quote_id_fkey;
ALTER TABLE public.invoices DROP CONSTRAINT IF EXISTS invoices_quote_id_fkey;
ALTER TABLE public.invoices DROP CONSTRAINT IF EXISTS invoices_client_id_fkey;
ALTER TABLE public.quotes DROP CONSTRAINT IF EXISTS quotes_client_id_fkey;
COMMIT;
