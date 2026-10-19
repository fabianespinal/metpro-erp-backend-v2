-- Rollback X-01 backfill: remove only the projects it created, and only if nothing was added to them.
BEGIN;
DELETE FROM public.projects p
WHERE p.notes = 'Creado por backfill X-01 (2026-10-18)'
  AND NOT EXISTS (SELECT 1 FROM public.expenses e WHERE e.project_id = p.id);
COMMIT;
