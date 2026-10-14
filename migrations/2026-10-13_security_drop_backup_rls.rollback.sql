-- Rollback for 2026-10-13_security_drop_backup_rls.sql
-- Restores RLS state only. The dropped users_backup table cannot be restored
-- from this file. Restore it from a backup if needed.
BEGIN;

ALTER TABLE public.invoices         DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_items    DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_payments DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.expenses         DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.contacts         DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.projects         DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.users            DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.conduces         DISABLE ROW LEVEL SECURITY;

COMMIT;
