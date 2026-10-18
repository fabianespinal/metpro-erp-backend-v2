-- 2026-10-18: Project Cost Ledger. Link expenses to projects.
-- expenses.project_id already existed as free TEXT (0 rows set). projects.id is INTEGER.
-- Approved: convert the existing column to INTEGER NULL with a foreign key; deleting a project
-- that has expenses is blocked (NO ACTION, no cascade). No default, no data migration.
-- Aborts if any existing value is non-numeric or points to a missing project.
BEGIN;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM expenses
             WHERE project_id IS NOT NULL AND btrim(project_id) <> '' AND btrim(project_id) !~ '^[0-9]+$') THEN
    RAISE EXCEPTION 'expenses.project_id has non-numeric values; migration aborted';
  END IF;
  IF EXISTS (SELECT 1 FROM expenses e
             WHERE btrim(coalesce(e.project_id, '')) ~ '^[0-9]+$'
               AND NOT EXISTS (SELECT 1 FROM projects p WHERE p.id = btrim(e.project_id)::integer)) THEN
    RAISE EXCEPTION 'expenses.project_id points to missing projects; migration aborted';
  END IF;
END $$;
ALTER TABLE public.expenses
  ALTER COLUMN project_id TYPE integer USING NULLIF(btrim(project_id), '')::integer;
ALTER TABLE public.expenses
  ADD CONSTRAINT expenses_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE NO ACTION;
CREATE INDEX IF NOT EXISTS idx_expenses_project_id ON public.expenses (project_id);
COMMIT;
