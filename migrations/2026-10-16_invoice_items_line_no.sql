-- 2026-10-16: stable line order for invoice_items (Set 6, supports F2).
-- NOT APPLIED. Requires explicit approval to run on production.
-- Rollback: 2026-10-16_invoice_items_line_no.rollback.sql
--
-- invoice_items.id is a random UUID, so it cannot order lines. Until this runs,
-- the app orders by ctid (insertion order; rows are never updated).
-- After applying, a follow-up code change should:
--   - write line_no on convert (1..n in quote order), and
--   - ORDER BY line_no, ctid in invoices.service._invoice_lines and get_invoice_by_id.
-- That code change is NOT in this branch: it would fail until the column exists.

BEGIN;

ALTER TABLE public.invoice_items ADD COLUMN IF NOT EXISTS line_no integer;

-- Backfill current rows in their physical (insertion) order per invoice.
UPDATE public.invoice_items ii
SET line_no = s.rn
FROM (
    SELECT ctid AS row_ctid, row_number() OVER (PARTITION BY invoice_id ORDER BY ctid) AS rn
    FROM public.invoice_items
) s
WHERE ii.ctid = s.row_ctid AND ii.line_no IS NULL;

CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice_line ON public.invoice_items (invoice_id, line_no);

COMMIT;
