-- Rollback for 2026-10-18_expenses_project_fk.sql: back to free TEXT, links kept as text ids.
BEGIN;
DROP INDEX IF EXISTS public.idx_expenses_project_id;
ALTER TABLE public.expenses DROP CONSTRAINT IF EXISTS expenses_project_id_fkey;
ALTER TABLE public.expenses ALTER COLUMN project_id TYPE text USING project_id::text;
COMMIT;
