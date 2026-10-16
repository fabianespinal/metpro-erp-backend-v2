-- 2026-10-16: missing foreign keys + safe invoice_items cascade (Set 6).
-- NOT APPLIED. Requires explicit approval to run on production.
-- Rollback: 2026-10-16_foreign_keys.rollback.sql
--
-- Adds:
--   quotes.client_id        -> clients(id)       ON DELETE RESTRICT
--   invoices.client_id      -> clients(id)       ON DELETE RESTRICT
--   invoices.quote_id       -> quotes(quote_id)  ON DELETE RESTRICT
--   quote_items.quote_id    -> quotes(quote_id)  ON DELETE CASCADE
--   quote_items.product_id  -> products(id)      ON DELETE SET NULL
--   invoice_items.product_id-> products(id)      ON DELETE SET NULL
-- Changes:
--   invoice_items.invoice_id -> invoices(id): NO ACTION -> ON DELETE CASCADE
--     (the app deletes items explicitly too; this makes it safe for any path).
-- Left as is (documented): projects.client_id CASCADE (app now blocks deleting a
--   client with projects), conduces.invoice_id NO ACTION (table unused),
--   expenses.project_id/quote_id are text with no matching key type (no FK possible).
--
-- Every FK is created NOT VALID, then VALIDATEd, after an orphan pre-check that aborts.
-- Pre-check (read-only), each must return 0:
--   SELECT count(*) FROM quotes q LEFT JOIN clients c ON c.id=q.client_id WHERE q.client_id IS NOT NULL AND c.id IS NULL;
--   SELECT count(*) FROM invoices i LEFT JOIN clients c ON c.id=i.client_id WHERE i.client_id IS NOT NULL AND c.id IS NULL;
--   SELECT count(*) FROM invoices i LEFT JOIN quotes q ON q.quote_id=i.quote_id WHERE i.quote_id IS NOT NULL AND q.quote_id IS NULL;
--   SELECT count(*) FROM quote_items qi LEFT JOIN quotes q ON q.quote_id=qi.quote_id WHERE q.quote_id IS NULL;
--   SELECT count(*) FROM quote_items qi LEFT JOIN products p ON p.id=qi.product_id WHERE qi.product_id IS NOT NULL AND p.id IS NULL;
--   SELECT count(*) FROM invoice_items ii LEFT JOIN products p ON p.id=ii.product_id WHERE ii.product_id IS NOT NULL AND p.id IS NULL;
-- Production 2026-10-16: every pre-check above returned 0 (read-only run).

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.quotes q LEFT JOIN public.clients c ON c.id = q.client_id
               WHERE q.client_id IS NOT NULL AND c.id IS NULL) THEN
        RAISE EXCEPTION 'orphan quotes.client_id';
    END IF;
    IF EXISTS (SELECT 1 FROM public.invoices i LEFT JOIN public.clients c ON c.id = i.client_id
               WHERE i.client_id IS NOT NULL AND c.id IS NULL) THEN
        RAISE EXCEPTION 'orphan invoices.client_id';
    END IF;
    IF EXISTS (SELECT 1 FROM public.invoices i LEFT JOIN public.quotes q ON q.quote_id = i.quote_id
               WHERE i.quote_id IS NOT NULL AND q.quote_id IS NULL) THEN
        RAISE EXCEPTION 'orphan invoices.quote_id';
    END IF;
    IF EXISTS (SELECT 1 FROM public.quote_items qi LEFT JOIN public.quotes q ON q.quote_id = qi.quote_id
               WHERE q.quote_id IS NULL) THEN
        RAISE EXCEPTION 'orphan quote_items.quote_id';
    END IF;
    IF EXISTS (SELECT 1 FROM public.quote_items qi LEFT JOIN public.products p ON p.id = qi.product_id
               WHERE qi.product_id IS NOT NULL AND p.id IS NULL) THEN
        RAISE EXCEPTION 'orphan quote_items.product_id (run: UPDATE quote_items SET product_id = NULL WHERE ... )';
    END IF;
    IF EXISTS (SELECT 1 FROM public.invoice_items ii LEFT JOIN public.products p ON p.id = ii.product_id
               WHERE ii.product_id IS NOT NULL AND p.id IS NULL) THEN
        RAISE EXCEPTION 'orphan invoice_items.product_id';
    END IF;
END $$;

ALTER TABLE public.quotes ADD CONSTRAINT quotes_client_id_fkey
    FOREIGN KEY (client_id) REFERENCES public.clients(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE public.invoices ADD CONSTRAINT invoices_client_id_fkey
    FOREIGN KEY (client_id) REFERENCES public.clients(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE public.invoices ADD CONSTRAINT invoices_quote_id_fkey
    FOREIGN KEY (quote_id) REFERENCES public.quotes(quote_id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE public.quote_items ADD CONSTRAINT quote_items_quote_id_fkey
    FOREIGN KEY (quote_id) REFERENCES public.quotes(quote_id) ON DELETE CASCADE NOT VALID;
ALTER TABLE public.quote_items ADD CONSTRAINT quote_items_product_id_fkey
    FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE SET NULL NOT VALID;
ALTER TABLE public.invoice_items ADD CONSTRAINT invoice_items_product_id_fkey
    FOREIGN KEY (product_id) REFERENCES public.products(id) ON DELETE SET NULL NOT VALID;

ALTER TABLE public.invoice_items DROP CONSTRAINT invoice_items_invoice_id_fkey;
ALTER TABLE public.invoice_items ADD CONSTRAINT invoice_items_invoice_id_fkey
    FOREIGN KEY (invoice_id) REFERENCES public.invoices(id) ON DELETE CASCADE;

ALTER TABLE public.quotes VALIDATE CONSTRAINT quotes_client_id_fkey;
ALTER TABLE public.invoices VALIDATE CONSTRAINT invoices_client_id_fkey;
ALTER TABLE public.invoices VALIDATE CONSTRAINT invoices_quote_id_fkey;
ALTER TABLE public.quote_items VALIDATE CONSTRAINT quote_items_quote_id_fkey;
ALTER TABLE public.quote_items VALIDATE CONSTRAINT quote_items_product_id_fkey;
ALTER TABLE public.invoice_items VALIDATE CONSTRAINT invoice_items_product_id_fkey;

COMMIT;
