-- ============================================================
-- ROLLBACK: numeric(12,2) -> double precision for money fields
-- Pairs with: 2026-10-14_money_numeric.sql
-- Status:   Reversal file. Not run on production. Tested on local rehearsal (PostgreSQL 16).
-- Note:     Values rounded to 2 dp by the forward migration keep their rounded
--           value. Sub-cent digits lost in quotes.total_amount are not restored.
-- ============================================================

BEGIN;

ALTER TABLE products    ALTER COLUMN unit_price     TYPE double precision USING unit_price::double precision;

ALTER TABLE quote_items ALTER COLUMN quantity       TYPE double precision USING quantity::double precision;
ALTER TABLE quote_items ALTER COLUMN unit_price     TYPE double precision USING unit_price::double precision;
ALTER TABLE quote_items ALTER COLUMN discount_value TYPE double precision USING discount_value::double precision;
ALTER TABLE quote_items ALTER COLUMN discount_value SET DEFAULT 0;

ALTER TABLE quotes      ALTER COLUMN total_amount   TYPE double precision USING total_amount::double precision;

COMMIT;
