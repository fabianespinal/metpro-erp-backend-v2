-- ============================================================
-- P1: fix column defaults that stored literal quote characters
-- Target:   Supabase PostgreSQL (public schema)
-- Status:   NOT APPLIED. Run only after explicit approval.
-- Safe to re-run: SET DEFAULT is idempotent.
-- Existing rows are NOT changed. Check them with the verification query.
-- ============================================================

BEGIN;

ALTER TABLE quote_items ALTER COLUMN discount_type SET DEFAULT 'none';
ALTER TABLE quotes      ALTER COLUMN status        SET DEFAULT 'Draft';

COMMIT;

-- Verification (read-only). Expect 0 rows for the 'bad' checks.
-- SELECT 'quote_items.discount_type' AS col, COUNT(*) AS bad_rows
--   FROM quote_items WHERE discount_type LIKE '''%'''
-- UNION ALL
-- SELECT 'quotes.status', COUNT(*) FROM quotes WHERE status LIKE '''%''';
