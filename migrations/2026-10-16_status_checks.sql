-- 2026-10-16: CHECK constraints on quote and invoice status (Set 6).
-- NOT APPLIED. Requires explicit approval to run on production.
-- Rollback: 2026-10-16_status_checks.rollback.sql
--
-- Allowed values mirror the app matrices:
--   quotes:   Draft, Final, Sent, Approved, Rejected, Invoiced   (quotes/service.py QUOTE_STATUSES)
--   invoices: Pending, Paid, Cancelled, Overdue                  (invoices/service.py INVOICE_STATUSES)
-- invoices.status default changes from 'Draft' (never used by the app) to 'Pending'.
--
-- Pre-check (read-only). Both must return 0 rows:
--   SELECT status, count(*) FROM public.quotes WHERE status IS NULL OR status NOT IN
--     ('Draft','Final','Sent','Approved','Rejected','Invoiced') GROUP BY 1;
--   SELECT status, count(*) FROM public.invoices WHERE status NOT IN
--     ('Pending','Paid','Cancelled','Overdue') GROUP BY 1;
-- Production 2026-10-16: quotes Sent:1, Approved:1; invoices Cancelled:1. Passes.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.quotes WHERE status IS NULL OR status NOT IN
               ('Draft','Final','Sent','Approved','Rejected','Invoiced')) THEN
        RAISE EXCEPTION 'quotes.status has values outside the allowed set';
    END IF;
    IF EXISTS (SELECT 1 FROM public.invoices WHERE status NOT IN ('Pending','Paid','Cancelled','Overdue')) THEN
        RAISE EXCEPTION 'invoices.status has values outside the allowed set';
    END IF;
END $$;

ALTER TABLE public.quotes ALTER COLUMN status SET DEFAULT 'Draft';
ALTER TABLE public.quotes ALTER COLUMN status SET NOT NULL;
ALTER TABLE public.quotes ADD CONSTRAINT quotes_status_check
    CHECK (status IN ('Draft','Final','Sent','Approved','Rejected','Invoiced'));

ALTER TABLE public.invoices ALTER COLUMN status SET DEFAULT 'Pending';
ALTER TABLE public.invoices ADD CONSTRAINT invoices_status_check
    CHECK (status IN ('Pending','Paid','Cancelled','Overdue'));

COMMIT;
