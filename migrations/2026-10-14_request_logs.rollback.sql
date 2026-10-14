-- Rollback for 2026-10-14_request_logs.sql
-- DROP TABLE removes all logged rows. Export first if the audit data is needed.
BEGIN;

DROP INDEX IF EXISTS public.idx_request_logs_timestamp;
DROP TABLE IF EXISTS public.request_logs;

COMMIT;
