-- Rollback for the B-19 backfill. Production state before it: invoice 6 (F-10006) had line_no NULL on all 6 rows.
-- The app orders by line_no NULLS LAST, ctid, so NULL restores the old (ctid) order exactly.
UPDATE public.invoice_items SET line_no = NULL WHERE invoice_id = 6;
