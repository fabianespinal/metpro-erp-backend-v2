-- Rollback for 2026-10-23_status_history.sql. Refuses if any history row exists.
-- Turn STATUS_HISTORY_ENABLED off first.
BEGIN;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.status_history LIMIT 1) THEN
        RAISE EXCEPTION 'status_history has rows; export them before rollback';
    END IF;
END $$;
DROP TRIGGER IF EXISTS status_history_append_only ON public.status_history;
DROP TABLE IF EXISTS public.status_history;
DROP FUNCTION IF EXISTS public.status_history_block_change();
COMMIT;
