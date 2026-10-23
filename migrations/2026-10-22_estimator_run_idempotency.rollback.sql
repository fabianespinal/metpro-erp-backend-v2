-- Rollback for 2026-10-22_estimator_run_idempotency.sql.
BEGIN;
DROP INDEX IF EXISTS public.estimator_runs_idempotency_key_uq;
ALTER TABLE public.estimator_runs DROP COLUMN IF EXISTS idempotency_key;
COMMIT;
