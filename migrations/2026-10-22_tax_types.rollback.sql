-- Rollback for 2026-10-22_tax_types.sql.
-- Refuses to run if any document was issued with a type other than the default 18%:
-- the previous code would print and recompute those at 18%. Export them first.
BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.quotes   WHERE tax_type_code <> 'itbis_18')
    OR EXISTS (SELECT 1 FROM public.invoices WHERE tax_type_code <> 'itbis_18') THEN
        RAISE EXCEPTION 'Rollback blocked: documents exist with a tax type other than itbis_18';
    END IF;
END $$;

ALTER TABLE public.quotes   DROP COLUMN IF EXISTS tax_type_code, DROP COLUMN IF EXISTS tax_rate, DROP COLUMN IF EXISTS tax_label;
ALTER TABLE public.invoices DROP COLUMN IF EXISTS tax_type_code, DROP COLUMN IF EXISTS tax_rate, DROP COLUMN IF EXISTS tax_label;
DROP TABLE IF EXISTS public.tax_types;

COMMIT;
