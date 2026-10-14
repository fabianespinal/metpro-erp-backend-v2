-- ============================================================
-- Migration: drop users_backup, enable RLS on all public tables
-- Date:      2026-10-13
-- Status:    APPLIED to production. Date not recorded in this file.
-- Target:    Production Supabase, public schema
-- Idempotent: safe to re-run.
--
-- Effects:
--   - Drops public.users_backup (holds password hashes). IRREVERSIBLE.
--   - Enables RLS on 8 tables that lacked it. No policies are added.
--     The backend connects as the table owner and bypasses RLS.
--     The anon and authenticated roles lose direct table access.
--
-- Pre-check (read only): SELECT to_regclass('public.users_backup');
-- ============================================================

BEGIN;

DROP TABLE IF EXISTS public.users_backup;

ALTER TABLE public.invoices         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_items    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.expenses         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.contacts         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.projects         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.users            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conduces         ENABLE ROW LEVEL SECURITY;

COMMIT;
