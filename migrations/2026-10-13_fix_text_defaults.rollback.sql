-- Rollback for 2026-10-13_fix_text_defaults.sql (restores the previous, buggy defaults)
BEGIN;
ALTER TABLE quote_items ALTER COLUMN discount_type SET DEFAULT '''none''';
ALTER TABLE quotes      ALTER COLUMN status        SET DEFAULT '''Draft''';
COMMIT;
