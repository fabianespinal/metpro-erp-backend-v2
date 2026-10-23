-- Rollback for 2026-10-24_rfq.sql. Turn RFQ_ENABLED off first.
-- Refuses if any RFQ exists; export them before rollback.
BEGIN;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.rfqs LIMIT 1) THEN
        RAISE EXCEPTION 'rfqs has rows; export them before rollback';
    END IF;
END $$;
DROP TABLE IF EXISTS public.rfq_items;
DROP TABLE IF EXISTS public.rfqs;
DROP SEQUENCE IF EXISTS public.rfq_number_seq;
COMMIT;
