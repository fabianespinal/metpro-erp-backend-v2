-- A2 Payment correction and audit trail. Additive only. No existing row is changed.
--
-- Payments are never edited or deleted. A mistake is fixed by voiding the payment (reason required) and
-- recording a linked corrected payment, in one transaction.
--
--   created_at / created_by_user_id  who recorded the payment and when. NULL for the payments that existed
--                                    before this migration: that information was never captured, so none is invented.
--   backfilled                       true for every payment that existed before this migration, false for new ones.
--   corrects_payment_id              on a corrected payment: the voided payment it replaces.
--   correction_chain_id              on a corrected payment: the FIRST payment of its chain (A voided, B voided, C).
--                                    The first payment itself keeps NULL; its chain is COALESCE(correction_chain_id, id).
--
-- Void metadata (voided_at, void_reason, voided_by_user_id) already exists and stays the "corrected by / at" record
-- of the replaced payment; the corrected payment carries created_by / created_at.
BEGIN;

ALTER TABLE public.invoice_payments
    ADD COLUMN IF NOT EXISTS created_at          timestamptz,
    ADD COLUMN IF NOT EXISTS created_by_user_id  uuid    REFERENCES public.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS corrects_payment_id integer REFERENCES public.invoice_payments(id),
    ADD COLUMN IF NOT EXISTS correction_chain_id integer REFERENCES public.invoice_payments(id),
    ADD COLUMN IF NOT EXISTS backfilled          boolean NOT NULL DEFAULT true;

-- Existing rows keep NULL / true. New rows get the real values.
ALTER TABLE public.invoice_payments ALTER COLUMN backfilled SET DEFAULT false;
ALTER TABLE public.invoice_payments ALTER COLUMN created_at SET DEFAULT now();

-- A link and its chain exist together, and a payment cannot correct itself.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'invoice_payments_correction_pair_chk') THEN
        ALTER TABLE public.invoice_payments ADD CONSTRAINT invoice_payments_correction_pair_chk
            CHECK ((corrects_payment_id IS NULL) = (correction_chain_id IS NULL));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'invoice_payments_no_self_correction_chk') THEN
        ALTER TABLE public.invoice_payments ADD CONSTRAINT invoice_payments_no_self_correction_chk
            CHECK (corrects_payment_id IS NULL OR corrects_payment_id <> id);
    END IF;
END $$;

-- A payment is corrected at most once. A later fix corrects the corrected payment, which extends the chain.
CREATE UNIQUE INDEX IF NOT EXISTS invoice_payments_one_correction_idx
    ON public.invoice_payments (corrects_payment_id) WHERE corrects_payment_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS invoice_payments_chain_idx
    ON public.invoice_payments (correction_chain_id) WHERE correction_chain_id IS NOT NULL;

COMMIT;
