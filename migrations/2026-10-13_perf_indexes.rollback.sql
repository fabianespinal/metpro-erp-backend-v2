-- Rollback for 2026-10-13_perf_indexes.sql
-- Drops only indexes this migration names (idx_<table>_<col>).
-- Pre-existing indexes are never created or dropped by the migration.
DROP INDEX IF EXISTS idx_quote_items_quote_id;
DROP INDEX IF EXISTS idx_invoice_items_invoice_id;
DROP INDEX IF EXISTS idx_invoice_payments_invoice_id;
DROP INDEX IF EXISTS idx_conduces_invoice_id;
DROP INDEX IF EXISTS idx_invoices_client_id;
DROP INDEX IF EXISTS idx_invoices_contact_id;
DROP INDEX IF EXISTS idx_invoices_status;
DROP INDEX IF EXISTS idx_invoices_invoice_date;
DROP INDEX IF EXISTS idx_quotes_client_id;
DROP INDEX IF EXISTS idx_quotes_contact_id;
DROP INDEX IF EXISTS idx_quotes_status;
DROP INDEX IF EXISTS idx_quotes_created_at;
DROP INDEX IF EXISTS idx_contacts_company_id;
DROP INDEX IF EXISTS idx_expenses_created_at;
DROP INDEX IF EXISTS idx_projects_client_id;
DROP INDEX IF EXISTS idx_projects_created_at;
