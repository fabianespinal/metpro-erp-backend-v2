-- Rollback for 2026-10-22_product_dimensions.sql.
-- Refuses to run if any product has a dimension value: dropping the columns would destroy entered data.
BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.products WHERE length IS NOT NULL OR width IS NOT NULL OR height IS NOT NULL
               OR thickness IS NOT NULL OR area IS NOT NULL OR volume IS NOT NULL) THEN
        RAISE EXCEPTION 'Rollback blocked: products have dimension data. Export it first.';
    END IF;
END $$;

ALTER TABLE public.products DROP CONSTRAINT IF EXISTS products_dimensions_nonneg;
ALTER TABLE public.products
    DROP COLUMN IF EXISTS length, DROP COLUMN IF EXISTS width, DROP COLUMN IF EXISTS height,
    DROP COLUMN IF EXISTS thickness, DROP COLUMN IF EXISTS area, DROP COLUMN IF EXISTS volume,
    DROP COLUMN IF EXISTS area_manual, DROP COLUMN IF EXISTS volume_manual;

COMMIT;
