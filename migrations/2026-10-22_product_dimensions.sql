-- B3 Product dimensions. All estimation fields defined at once so no later migration is needed.
-- Foundation for the future estimation work; nothing reads them yet except the product form.
-- Additive and nullable: existing products keep every value, dimensions start empty.
-- Values are stored as entered. Nothing is derived or converted here (no assumptions about area or volume).
BEGIN;

ALTER TABLE public.products
    ADD COLUMN IF NOT EXISTS length          numeric(14,4),
    ADD COLUMN IF NOT EXISTS width           numeric(14,4),
    ADD COLUMN IF NOT EXISTS height          numeric(14,4),
    ADD COLUMN IF NOT EXISTS thickness       numeric(14,4),
    ADD COLUMN IF NOT EXISTS area            numeric(18,4),
    ADD COLUMN IF NOT EXISTS volume          numeric(18,4),
    ADD COLUMN IF NOT EXISTS unit_of_measure text;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'products_dimensions_nonneg') THEN
        ALTER TABLE public.products ADD CONSTRAINT products_dimensions_nonneg CHECK (
            (length    IS NULL OR length    >= 0) AND (width  IS NULL OR width  >= 0) AND
            (height    IS NULL OR height    >= 0) AND (thickness IS NULL OR thickness >= 0) AND
            (area      IS NULL OR area      >= 0) AND (volume IS NULL OR volume >= 0));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'products_unit_of_measure_len') THEN
        ALTER TABLE public.products ADD CONSTRAINT products_unit_of_measure_len CHECK (
            unit_of_measure IS NULL OR char_length(unit_of_measure) BETWEEN 1 AND 20);
    END IF;
END $$;

COMMIT;
