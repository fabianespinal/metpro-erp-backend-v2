-- Rollback. Restores the one pre-existing invoice label recorded on 2026-10-17.
UPDATE invoices SET invoice_number = 'INV-20261016020822'
WHERE invoice_number = 'F-10002' AND quote_id = 'b03cfa26-faf1-4bc7-9504-6ac66ed10001';
-- Any invoice created after the deploy keeps its F- label; set it by hand if needed.
ALTER TABLE invoice_items DROP COLUMN IF EXISTS category;
ALTER TABLE quote_items   DROP COLUMN IF EXISTS category;
ALTER TABLE conduces      DROP COLUMN IF EXISTS quote_number;
ALTER TABLE invoices      DROP COLUMN IF EXISTS quote_number;
