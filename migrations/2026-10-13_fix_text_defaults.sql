-- ============================================================
-- P1: fix column defaults that stored literal quote characters
-- Target:   Supabase PostgreSQL (public schema)
-- Status:   APPLIED to production 2026-10-13 (verified: defaults 'none' and 'Draft').
-- Safe to re-run: SET DEFAULT is idempotent.
-- Existing rows are NOT changed. Check them with the verification query.
-- ============================================================

BEGIN;

ALTER TABLE quote_items ALTER COLUMN discount_type SET DEFAULT 'none';
ALTER TABLE quotes      ALTER COLUMN status        SET DEFAULT 'Draft';

COMMIT;

-- Verification (read-only). Expect the two rows below with clean defaults.
-- SELECT table_name, column_name, column_default
-- FROM information_schema.columns
-- WHERE table_schema = 'public'
--   AND ((table_name = 'quote_items' AND column_name = 'discount_type')
--     OR (table_name = 'quotes' AND column_name = 'status'));
