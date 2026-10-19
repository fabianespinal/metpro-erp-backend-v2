-- Debug B-14 (approved 2026-10-18): void a payment entered by mistake, keeping the record.
-- Additive: three nullable columns. A voided payment is excluded from every balance, PDF and report.
ALTER TABLE public.invoice_payments ADD COLUMN IF NOT EXISTS voided_at timestamptz NULL;
ALTER TABLE public.invoice_payments ADD COLUMN IF NOT EXISTS void_reason text NULL;
ALTER TABLE public.invoice_payments ADD COLUMN IF NOT EXISTS voided_by_user_id uuid NULL
    REFERENCES public.users(id) ON DELETE SET NULL;
