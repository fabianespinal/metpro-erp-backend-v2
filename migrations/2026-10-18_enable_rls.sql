-- 2026-10-18: enable Row Level Security on every public table (Supabase advisory rls_disabled).
-- No policies: the anon/authenticated Data API roles see nothing. The backend connects as the
-- table owner (postgres, BYPASSRLS), proven by request_logs (RLS on, 0 policies) receiving inserts.
ALTER TABLE public.clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quote_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conduces ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.expenses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.template_packs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.template_pack_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.template_pack_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cover_page_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.terms_settings ENABLE ROW LEVEL SECURITY;
