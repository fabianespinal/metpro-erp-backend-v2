-- Engineering Estimate I3-a: double-click protection for Generate.
-- Additive. estimator_runs is append-only (no UPDATE), so the key is written at insert.
BEGIN;
ALTER TABLE public.estimator_runs ADD COLUMN IF NOT EXISTS idempotency_key uuid;
CREATE UNIQUE INDEX IF NOT EXISTS estimator_runs_idempotency_key_uq ON public.estimator_runs (idempotency_key);
COMMIT;
