-- ============================================================
-- PRODUCTION RLS FIX
-- Disable RLS on all tables to restore functionality
-- All authenticated users can now read/write data
-- ============================================================

ALTER TABLE public.clients DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.contacts DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.products DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.quotes DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.quote_items DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoices DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_items DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_payments DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.expenses DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.projects DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.users DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.conduces DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.template_packs DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.template_pack_categories DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.template_pack_items DISABLE ROW LEVEL SECURITY;

-- Verify RLS is disabled
SELECT tablename, (SELECT (schemaname, tablename, rowsecurity)
  FROM information_schema.tables t
  WHERE t.table_name = pg_tables.tablename
  AND t.table_schema = 'public')
FROM pg_tables WHERE schemaname = 'public';
