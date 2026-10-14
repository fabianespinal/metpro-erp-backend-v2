-- Rollback for 2026-10-13_quote_public_token.sql
BEGIN;
DROP INDEX IF EXISTS quotes_public_token_key;
ALTER TABLE quotes DROP COLUMN IF EXISTS public_token;
COMMIT;
