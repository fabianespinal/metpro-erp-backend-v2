-- Rollback for 2026-10-13_invoice_public_token.sql
-- Only run if the backend has been reverted to a version that does not read public_token.
BEGIN;
DROP INDEX IF EXISTS invoices_public_token_key;
ALTER TABLE invoices DROP COLUMN IF EXISTS public_token;
COMMIT;
