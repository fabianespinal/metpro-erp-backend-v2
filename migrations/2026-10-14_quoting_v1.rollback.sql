-- Rollback for 2026-10-14_quoting_v1.sql
-- WARNING: drops quoting v1 data (template packs, item types, totals, terms, finalize time).
-- Run only after explicit approval. Refuses to run if any quote has a NULL public_token,
-- because restoring NOT NULL would fail. Resolve those rows first.
BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM quotes WHERE public_token IS NULL) THEN
        RAISE EXCEPTION 'Rollback stopped: quotes with NULL public_token exist. Assign tokens first.';
    END IF;
END
$$;

ALTER TABLE quotes ALTER COLUMN public_token SET DEFAULT gen_random_uuid();
ALTER TABLE quotes ALTER COLUMN public_token SET NOT NULL;

ALTER TABLE quotes
    DROP COLUMN IF EXISTS finalized_at,
    DROP COLUMN IF EXISTS terms,
    DROP COLUMN IF EXISTS grand_total,
    DROP COLUMN IF EXISTS tax_amount,
    DROP COLUMN IF EXISTS discount_total,
    DROP COLUMN IF EXISTS subtotal;

ALTER TABLE quote_items DROP CONSTRAINT IF EXISTS quote_items_item_type_check;
ALTER TABLE quote_items
    DROP COLUMN IF EXISTS description,
    DROP COLUMN IF EXISTS item_type;

DROP TABLE IF EXISTS template_pack_items;
DROP TABLE IF EXISTS template_pack_categories;
DROP TABLE IF EXISTS template_packs;

COMMIT;
