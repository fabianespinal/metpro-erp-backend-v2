-- Rollback of activation. Allowed only while no run exists. Returns version 1.0 to draft.
BEGIN;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM public.estimator_runs) THEN RAISE EXCEPTION 'estimator runs exist: do not return the version to draft'; END IF;
END $$;
UPDATE public.estimator_versions SET status = 'draft', activated_at = NULL
WHERE status = 'active' AND model_id = (SELECT id FROM public.estimator_models WHERE name = 'Nave Industrial') AND version = '1.0';
COMMIT;
