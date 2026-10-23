-- Rollback for 2026-10-22_estimator_schema.sql.
-- Refuses to run while runs, audit rows or typed quotes exist: dropping them would lose history.
BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.estimator_runs)
    OR EXISTS (SELECT 1 FROM public.quote_edit_audit)
    OR EXISTS (SELECT 1 FROM public.quotes WHERE quote_type IS NOT NULL) THEN
        RAISE EXCEPTION 'estimator rollback refused: runs, audit rows or typed quotes exist';
    END IF;
END $$;

DROP TABLE IF EXISTS public.quote_edit_audit;
DROP TABLE IF EXISTS public.estimator_runs;
DROP TABLE IF EXISTS public.estimator_materials;
DROP TABLE IF EXISTS public.estimator_constants;
DROP TABLE IF EXISTS public.estimator_profiles;
DROP TABLE IF EXISTS public.estimator_versions;
DROP TABLE IF EXISTS public.estimator_models;
ALTER TABLE public.quotes DROP COLUMN IF EXISTS quote_type;
DROP FUNCTION IF EXISTS public.estimator_freeze_children();
DROP FUNCTION IF EXISTS public.estimator_block_change();

COMMIT;
