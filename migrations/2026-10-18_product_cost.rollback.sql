-- Rollback for 2026-10-18_product_cost.sql (drops the cost values).
ALTER TABLE public.products DROP COLUMN IF EXISTS cost;
