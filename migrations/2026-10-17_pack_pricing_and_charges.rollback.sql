-- Rollback for 2026-10-17_pack_pricing_and_charges.sql. Drops override prices and pack charges.
BEGIN;
DROP TABLE IF EXISTS public.template_pack_charges;
ALTER TABLE public.template_pack_items DROP COLUMN IF EXISTS pack_price_override;
COMMIT;
