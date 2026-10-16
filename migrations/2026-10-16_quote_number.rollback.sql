-- Rollback for 2026-10-16_quote_number.sql. NOT APPLIED.
BEGIN;

ALTER TABLE quotes DROP CONSTRAINT IF EXISTS quotes_quote_number_key;
ALTER TABLE quotes ALTER COLUMN quote_number DROP DEFAULT;
ALTER TABLE quotes DROP COLUMN IF EXISTS quote_number;
DROP SEQUENCE IF EXISTS quote_number_seq;

COMMIT;
