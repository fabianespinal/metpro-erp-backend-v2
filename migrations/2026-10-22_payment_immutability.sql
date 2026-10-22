-- A2b (APPROVED 2026-10-22): database-level immutability for payments.
-- Enforced for every client, including manual SQL:
--   - no DELETE of a payment row;
--   - no UPDATE of any column, EXCEPT the one-time void: voided_at, void_reason and voided_by_user_id may go from
--     empty to filled on a live payment (a void needs a reason and a user). A voided payment never changes again.
-- Consequence: deleting a user who created or voided a payment fails (the FK would null the audit column).
--   Deactivate such users instead.
-- Cascade from deleting an invoice still fails, which matches the app rule (an invoice with payments cannot be deleted).
-- TRUNCATE is not blocked (test databases use it).
-- Rollback: 2026-10-22_payment_immutability.rollback.sql (drops the triggers; no data change).
BEGIN;

CREATE OR REPLACE FUNCTION public.invoice_payments_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'invoice_payments rows are never deleted (payment %)', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.voided_at IS NOT NULL THEN
        RAISE EXCEPTION 'a voided payment cannot be changed (payment %)', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['voided_at', 'void_reason', 'voided_by_user_id'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['voided_at', 'void_reason', 'voided_by_user_id']) THEN
        RAISE EXCEPTION 'invoice_payments rows are not edited; void and record a corrected payment (payment %)', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.voided_at IS NULL OR btrim(coalesce(NEW.void_reason, '')) = '' OR NEW.voided_by_user_id IS NULL THEN
        RAISE EXCEPTION 'a void needs a timestamp, a reason and a user (payment %)', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS invoice_payments_guard_upd ON public.invoice_payments;
CREATE TRIGGER invoice_payments_guard_upd BEFORE UPDATE ON public.invoice_payments
    FOR EACH ROW EXECUTE FUNCTION public.invoice_payments_guard();

DROP TRIGGER IF EXISTS invoice_payments_guard_del ON public.invoice_payments;
CREATE TRIGGER invoice_payments_guard_del BEFORE DELETE ON public.invoice_payments
    FOR EACH ROW EXECUTE FUNCTION public.invoice_payments_guard();

COMMIT;
