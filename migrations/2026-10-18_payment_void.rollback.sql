-- Rollback B-14. Run only after reverting the code (it reads these columns).
-- WARNING: voided payments would count again. Check first:
--   SELECT id, invoice_id, amount, voided_at FROM public.invoice_payments WHERE voided_at IS NOT NULL;
-- If any rows exist, restore balances by hand before dropping the columns.
ALTER TABLE public.invoice_payments DROP COLUMN IF EXISTS voided_by_user_id;
ALTER TABLE public.invoice_payments DROP COLUMN IF EXISTS void_reason;
ALTER TABLE public.invoice_payments DROP COLUMN IF EXISTS voided_at;
