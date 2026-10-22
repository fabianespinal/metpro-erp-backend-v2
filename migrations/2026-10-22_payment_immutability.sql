-- A2b (OPTIONAL, separate approval): database-level immutability for payments.
-- Blocks, for any client including manual SQL:
--   - changing invoice_id, amount, payment_date, method or notes of a payment;
--   - un-voiding, or changing the void reason / voider of a voided payment;
--   - deleting a payment row.
-- Allowed: the one-time void (voided_at, void_reason, voided_by_user_id set on a live payment).
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
    IF NEW.invoice_id   IS DISTINCT FROM OLD.invoice_id
    OR NEW.amount       IS DISTINCT FROM OLD.amount
    OR NEW.payment_date IS DISTINCT FROM OLD.payment_date
    OR NEW.method       IS DISTINCT FROM OLD.method
    OR NEW.notes        IS DISTINCT FROM OLD.notes THEN
        RAISE EXCEPTION 'invoice_payments rows are not edited; void and record a corrected payment (payment %)', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.voided_at IS NOT NULL
       AND (NEW.voided_at          IS DISTINCT FROM OLD.voided_at
         OR NEW.void_reason        IS DISTINCT FROM OLD.void_reason
         OR NEW.voided_by_user_id  IS DISTINCT FROM OLD.voided_by_user_id) THEN
        RAISE EXCEPTION 'a voided payment cannot be changed (payment %)', OLD.id
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
