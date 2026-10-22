-- Rollback for 2026-10-22_print_on_pdf.sql.
-- Refuses to run while any line is hidden: the previous code would print it to customers.
-- Set the lines back to visible first (or accept that they will print), then run this.
BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.quote_items         WHERE print_on_pdf = false)
    OR EXISTS (SELECT 1 FROM public.invoice_items       WHERE print_on_pdf = false)
    OR EXISTS (SELECT 1 FROM public.template_pack_items WHERE print_on_pdf = false) THEN
        RAISE EXCEPTION 'Rollback blocked: hidden lines exist (print_on_pdf = false). Rolling back would print them to customers.';
    END IF;
END $$;

ALTER TABLE public.template_pack_items DROP COLUMN IF EXISTS print_on_pdf;
ALTER TABLE public.quote_items         DROP COLUMN IF EXISTS print_on_pdf;
ALTER TABLE public.invoice_items       DROP COLUMN IF EXISTS print_on_pdf;

COMMIT;
