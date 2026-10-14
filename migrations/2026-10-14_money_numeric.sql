-- ============================================================
-- Money fields: double precision -> numeric(12,2)
-- Target:   Supabase PostgreSQL (public schema)
-- Status:   NOT APPLIED. Requires explicit approval before running.
-- Option:   A (quotes.total_amount rounded to 2 dp)
-- Scope:
--   products.unit_price
--   quote_items.quantity
--   quote_items.unit_price
--   quote_items.discount_value   (default 0)
--   quotes.total_amount
-- Safety:   Fails before any change if any column is not double precision.
--           Runs in one transaction. Rollback: 2026-10-14_money_numeric.rollback.sql
-- Module 1 evidence: no values over 2 dp except quotes.total_amount (2 of 4 rows).
-- ============================================================

BEGIN;

-- Guard: every target column must currently be double precision.
DO $$
DECLARE
    bad_count integer;
BEGIN
    SELECT count(*) INTO bad_count
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND (table_name, column_name) IN (
        ('products',    'unit_price'),
        ('quote_items', 'quantity'),
        ('quote_items', 'unit_price'),
        ('quote_items', 'discount_value'),
        ('quotes',      'total_amount')
      )
      AND data_type <> 'double precision';

    IF bad_count <> 0 THEN
        RAISE EXCEPTION 'Guard failed: % target column(s) are not double precision. Aborting.', bad_count;
    END IF;
END $$;

ALTER TABLE products    ALTER COLUMN unit_price     TYPE numeric(12,2) USING ROUND(unit_price::numeric, 2);

ALTER TABLE quote_items ALTER COLUMN quantity       TYPE numeric(12,2) USING ROUND(quantity::numeric, 2);
ALTER TABLE quote_items ALTER COLUMN unit_price     TYPE numeric(12,2) USING ROUND(unit_price::numeric, 2);
ALTER TABLE quote_items ALTER COLUMN discount_value TYPE numeric(12,2) USING ROUND(discount_value::numeric, 2);
ALTER TABLE quote_items ALTER COLUMN discount_value SET DEFAULT 0;

ALTER TABLE quotes      ALTER COLUMN total_amount   TYPE numeric(12,2) USING ROUND(total_amount::numeric, 2);

COMMIT;

-- Verification (read-only). Expect 5 rows, all numeric, precision 12, scale 2.
-- SELECT table_name, column_name, data_type, numeric_precision, numeric_scale, column_default
-- FROM information_schema.columns
-- WHERE table_schema = 'public'
--   AND (table_name, column_name) IN (
--     ('products','unit_price'), ('quote_items','quantity'), ('quote_items','unit_price'),
--     ('quote_items','discount_value'), ('quotes','total_amount'))
-- ORDER BY table_name, column_name;
