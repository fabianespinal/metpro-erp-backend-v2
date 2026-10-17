-- Document numbering chain (Q-/F-/C-) and template-pack category headings.
-- Additive. Safe for the previous backend (it ignores the new columns).
-- Apply BEFORE deploying the matching backend.

ALTER TABLE invoices    ADD COLUMN IF NOT EXISTS quote_number bigint;
ALTER TABLE conduces    ADD COLUMN IF NOT EXISTS quote_number bigint;
ALTER TABLE quote_items ADD COLUMN IF NOT EXISTS category text;
ALTER TABLE invoice_items ADD COLUMN IF NOT EXISTS category text;

-- Backfill the originating quote number on existing invoices.
UPDATE invoices i
SET quote_number = q.quote_number
FROM quotes q
WHERE TRIM(q.quote_id) = TRIM(i.quote_id) AND i.quote_number IS NULL;

-- Existing invoice labels move to the chain: INV-<timestamp> -> F-<quote_number>.
-- invoice_number is unique and there is one invoice per quote, so no collision.
UPDATE invoices
SET invoice_number = 'F-' || quote_number
WHERE quote_number IS NOT NULL AND invoice_number LIKE 'INV-%';
