-- Rollback for 2026-10-16_created_by.sql. NOT APPLIED.
-- Drops the creator reference on quotes and invoices. Creator data is lost.

BEGIN;

ALTER TABLE public.quotes DROP COLUMN IF EXISTS created_by_user_id;
ALTER TABLE public.invoices DROP COLUMN IF EXISTS created_by_user_id;

COMMIT;
