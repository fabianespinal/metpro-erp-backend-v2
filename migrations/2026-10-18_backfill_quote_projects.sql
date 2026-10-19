-- X-01 (approved 2026-10-18): create the missing project for every Approved or Invoiced quote.
-- Production today: Q-10002 (Approved) and Q-10006 (Invoiced, F-10006).
-- Same fields as projects.service.create_project_from_quote:
--   name        = quotes.project_name, else 'Proyecto Q-<n>'
--   description = first 3 line names, max 200 chars
--   job site    = client address
--   status      = 'pending'
--   start_date  = date of the quote's active invoice; else today in Santo Domingo
-- Idempotent: quotes that already have a project are skipped (unique index on projects.quote_id).
-- Rollback: 2026-10-18_backfill_quote_projects.rollback.sql (deletes only the rows created here).

BEGIN;

INSERT INTO public.projects (client_id, name, description, status, start_date, job_site_address, quote_id, quote_number, notes)
SELECT q.client_id,
       COALESCE(NULLIF(TRIM(q.project_name), ''), 'Proyecto Q-' || q.quote_number),
       NULLIF(LEFT((SELECT string_agg(x.product_name, ', ' ORDER BY x.id)
                    FROM (SELECT id, product_name FROM public.quote_items
                          WHERE quote_id = q.quote_id AND COALESCE(product_name, '') <> ''
                          ORDER BY id LIMIT 3) x), 200), ''),
       'pending',
       COALESCE((SELECT MAX(i.invoice_date)::date FROM public.invoices i
                 WHERE i.quote_id = q.quote_id AND i.status <> 'Cancelled'),
                (now() AT TIME ZONE 'America/Santo_Domingo')::date),
       c.address,
       q.quote_id,
       q.quote_number,
       'Creado por backfill X-01 (2026-10-18)'
FROM public.quotes q
LEFT JOIN public.clients c ON c.id = q.client_id
WHERE q.status IN ('Approved', 'Invoiced')
  AND NOT EXISTS (SELECT 1 FROM public.projects p WHERE p.quote_id = q.quote_id)
ON CONFLICT (quote_id) WHERE quote_id IS NOT NULL DO NOTHING;

COMMIT;
