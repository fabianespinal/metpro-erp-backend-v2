-- 2026-10-19 (debug B-19): fill invoice_items.line_no for rows created before the code wrote it.
-- Data only; no schema change. The column and index already exist.
-- Numbers each affected invoice 1..n in physical insertion order (what the app used until now).
-- Rollback: 2026-10-19_invoice_items_line_no_backfill.rollback.sql (affected invoice ids are listed there).
BEGIN;
UPDATE public.invoice_items ii
SET line_no = s.rn
FROM (
    SELECT ctid AS row_ctid, row_number() OVER (PARTITION BY invoice_id ORDER BY ctid) AS rn
    FROM public.invoice_items
    WHERE invoice_id IN (SELECT invoice_id FROM public.invoice_items WHERE line_no IS NULL)
) s
WHERE ii.ctid = s.row_ctid;
COMMIT;
