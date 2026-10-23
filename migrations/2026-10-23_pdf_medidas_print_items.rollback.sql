-- Rollback for 2026-10-23_pdf_medidas_print_items.sql.
-- Refuses to run while any data uses the new columns (dropping them would lose units, or would
-- start printing item tables on quotes where the user switched them off).
-- Clear the data first (UPDATE ... SET unit_of_measure = NULL / print_items = true), then run this.
BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.products      WHERE unit_of_measure IS NOT NULL)
    OR EXISTS (SELECT 1 FROM public.quote_items   WHERE unit_of_measure IS NOT NULL)
    OR EXISTS (SELECT 1 FROM public.invoice_items WHERE unit_of_measure IS NOT NULL)
    OR EXISTS (SELECT 1 FROM public.quotes        WHERE print_items = false)
    OR EXISTS (SELECT 1 FROM public.invoices      WHERE print_items = false) THEN
        RAISE EXCEPTION 'Rollback blocked: units of measure or print_items = false exist. Clear them first.';
    END IF;
END $$;

ALTER TABLE public.invoices      DROP COLUMN IF EXISTS print_items;
ALTER TABLE public.quotes        DROP COLUMN IF EXISTS print_items;
ALTER TABLE public.invoice_items DROP COLUMN IF EXISTS unit_of_measure;
ALTER TABLE public.quote_items   DROP COLUMN IF EXISTS unit_of_measure;
ALTER TABLE public.products      DROP COLUMN IF EXISTS unit_of_measure;

COMMIT;
