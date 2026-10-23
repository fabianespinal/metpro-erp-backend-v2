-- Rollback for 2026-10-24_purchase_orders.sql. Turn PO_ENABLED off first.
-- Refuses if any purchase order exists; export them before rollback.
BEGIN;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.purchase_orders LIMIT 1) THEN
        RAISE EXCEPTION 'purchase_orders has rows; export them before rollback';
    END IF;
END $$;
DROP TABLE IF EXISTS public.po_items;
DROP TABLE IF EXISTS public.purchase_orders;
DROP SEQUENCE IF EXISTS public.po_number_seq;
COMMIT;
