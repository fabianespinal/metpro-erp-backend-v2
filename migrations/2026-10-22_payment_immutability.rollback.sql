BEGIN;
DROP TRIGGER IF EXISTS invoice_payments_guard_upd ON public.invoice_payments;
DROP TRIGGER IF EXISTS invoice_payments_guard_del ON public.invoice_payments;
DROP FUNCTION IF EXISTS public.invoice_payments_guard();
COMMIT;
