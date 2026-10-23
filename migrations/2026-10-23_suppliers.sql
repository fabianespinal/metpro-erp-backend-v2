-- Suplidores (P2, 2026-10-23). Additive only. One new table; nothing existing changes.
-- Separate from clients on purpose: clients feed quotes, invoices, reports and the dashboard count.
-- Nothing reads or writes this table until SUPPLIERS_ENABLED=true on the backend.
-- is_dummy marks test rows so the go-live reset can delete them in one query.
BEGIN;

CREATE TABLE IF NOT EXISTS public.suppliers (
    id            bigserial PRIMARY KEY,
    company_name  text        NOT NULL CHECK (btrim(company_name) <> ''),
    contact_name  text,
    email         text,
    phone         text,
    address       text,
    tax_id        text,                              -- RNC
    notes         text,
    is_active     boolean     NOT NULL DEFAULT true,
    is_dummy      boolean     NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS suppliers_tax_id_uniq ON public.suppliers (tax_id) WHERE tax_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS suppliers_email_uniq  ON public.suppliers (lower(email)) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS suppliers_name_idx ON public.suppliers (lower(company_name));

ALTER TABLE public.suppliers ENABLE ROW LEVEL SECURITY;

COMMIT;
