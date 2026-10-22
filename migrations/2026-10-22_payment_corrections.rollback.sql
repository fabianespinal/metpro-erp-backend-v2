-- Rollback for 2026-10-22_payment_corrections.sql.
-- Refuses to run if any correction exists: the links and chains would be lost. Export them first.
-- Balances stay correct either way (voided payments stay voided).
BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.invoice_payments WHERE corrects_payment_id IS NOT NULL)
    OR EXISTS (SELECT 1 FROM public.invoice_payments WHERE created_by_user_id IS NOT NULL) THEN
        RAISE EXCEPTION 'Rollback blocked: payment corrections or creator records exist. Export them first.';
    END IF;
END $$;

DROP INDEX IF EXISTS public.invoice_payments_chain_idx;
DROP INDEX IF EXISTS public.invoice_payments_one_correction_idx;
ALTER TABLE public.invoice_payments
    DROP CONSTRAINT IF EXISTS invoice_payments_no_self_correction_chk,
    DROP CONSTRAINT IF EXISTS invoice_payments_correction_pair_chk,
    DROP COLUMN IF EXISTS backfilled,
    DROP COLUMN IF EXISTS correction_chain_id,
    DROP COLUMN IF EXISTS corrects_payment_id,
    DROP COLUMN IF EXISTS created_by_user_id,
    DROP COLUMN IF EXISTS created_at;

COMMIT;
