-- Rollback for 2026-10-23_suppliers.sql. Turn SUPPLIERS_ENABLED off first.
-- Refuses if any real (non-dummy) supplier exists; export them before rollback.
BEGIN;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.suppliers WHERE NOT is_dummy LIMIT 1) THEN
        RAISE EXCEPTION 'suppliers has real rows; export them before rollback';
    END IF;
END $$;
DROP TABLE IF EXISTS public.suppliers;
COMMIT;
