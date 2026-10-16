-- 2026-10-16: created_by_user_id on quotes and invoices.
-- Stores users.id. Display name is joined at read time (full_name, fallback username).
-- No backfill: existing rows stay NULL and display "—".
-- Deleting a user sets the reference to NULL, so quotes and invoices are kept.
-- NOT APPLIED. Requires explicit approval to run on production.
-- Rollback: migrations/2026-10-16_created_by.rollback.sql

BEGIN;

ALTER TABLE public.quotes
    ADD COLUMN IF NOT EXISTS created_by_user_id uuid REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE public.invoices
    ADD COLUMN IF NOT EXISTS created_by_user_id uuid REFERENCES public.users(id) ON DELETE SET NULL;

COMMIT;
