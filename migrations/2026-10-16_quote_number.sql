-- 2026-10-16: quote number sequence (Option A)
-- Printed quote number starts at 10001. Assigned at insert via column default.
-- NOT APPLIED. Requires explicit approval to run on production.
-- Rollback: migrations/2026-10-16_quote_number.rollback.sql

BEGIN;

CREATE SEQUENCE IF NOT EXISTS quote_number_seq START WITH 10001;

ALTER TABLE quotes ADD COLUMN IF NOT EXISTS quote_number bigint;

-- Backfill existing rows in creation order.
WITH numbered AS (
    SELECT quote_id, nextval('quote_number_seq') AS n
    FROM quotes
    WHERE quote_number IS NULL
    ORDER BY created_at, quote_id
)
UPDATE quotes q
SET quote_number = numbered.n
FROM numbered
WHERE q.quote_id = numbered.quote_id;

-- New rows get the next number at insert.
ALTER TABLE quotes ALTER COLUMN quote_number SET DEFAULT nextval('quote_number_seq');
ALTER TABLE quotes ALTER COLUMN quote_number SET NOT NULL;
ALTER TABLE quotes ADD CONSTRAINT quotes_quote_number_key UNIQUE (quote_number);

COMMIT;
