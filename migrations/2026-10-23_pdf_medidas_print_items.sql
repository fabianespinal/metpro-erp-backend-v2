-- PDF update: unit of measure ("Medidas") and the per-quote "show products on the PDF" checkbox.
-- Additive only. Every new column is nullable or has a default, so the current code keeps working
-- before and after this runs. Run it BEFORE the backend that uses it is deployed.
--   products.unit_of_measure       free text (Unidad, Ft, M, M2, Ton, Lb, Set ...), no fixed list
--   quote_items.unit_of_measure    copied from the product, editable per line
--   invoice_items.unit_of_measure  copied from the quote line at conversion
--   quotes.print_items             false = the PDF shows heading, charges and totals only (totals unchanged)
--   invoices.print_items           copied from the quote at conversion
-- Rollback: 2026-10-23_pdf_medidas_print_items.rollback.sql (refuses while any data uses the new columns).
BEGIN;

ALTER TABLE public.products      ADD COLUMN IF NOT EXISTS unit_of_measure text;
ALTER TABLE public.quote_items   ADD COLUMN IF NOT EXISTS unit_of_measure text;
ALTER TABLE public.invoice_items ADD COLUMN IF NOT EXISTS unit_of_measure text;
ALTER TABLE public.quotes        ADD COLUMN IF NOT EXISTS print_items boolean NOT NULL DEFAULT true;
ALTER TABLE public.invoices      ADD COLUMN IF NOT EXISTS print_items boolean NOT NULL DEFAULT true;

COMMIT;
