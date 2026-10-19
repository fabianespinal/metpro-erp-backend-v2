-- 2026-10-18: Product Cost module. Internal unit cost per product, used only for estimated
-- cost and margin (display). No default, no data migration, no constraint changes.
-- The API validates cost >= 0. RLS stays on; the backend connects as owner.
ALTER TABLE public.products ADD COLUMN IF NOT EXISTS cost numeric(12,2) NULL;
