-- A3 Visibility controls: line-level print_on_pdf.
-- false = the line counts in every total and shows on internal screens, but never prints on customer PDFs,
-- emailed PDFs, conduces or public pages. Hide only: nothing is redistributed across visible lines.
-- Additive. Existing rows become true through a constant default, so nothing changes for them.
BEGIN;

ALTER TABLE public.template_pack_items ADD COLUMN IF NOT EXISTS print_on_pdf boolean NOT NULL DEFAULT true;
ALTER TABLE public.quote_items         ADD COLUMN IF NOT EXISTS print_on_pdf boolean NOT NULL DEFAULT true;
ALTER TABLE public.invoice_items       ADD COLUMN IF NOT EXISTS print_on_pdf boolean NOT NULL DEFAULT true;

COMMIT;
