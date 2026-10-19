-- Rollback X-05 (after reverting the code). Archived products would reappear in the catalog:
--   SELECT id, name FROM public.products WHERE archived_at IS NOT NULL;
ALTER TABLE public.products DROP COLUMN IF EXISTS archived_at;
