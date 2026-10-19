-- Debug X-05: products used on quote/invoice lines are archived instead of deleted, so the lines
-- keep their product link (cost estimates, variance). Additive: one nullable column.
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS archived_at timestamptz NULL;
