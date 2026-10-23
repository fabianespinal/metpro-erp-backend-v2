-- RFQ (P3a, 2026-10-24). Additive only. Two new tables and one sequence; nothing existing changes.
-- An RFQ NEVER carries prices: there is no price column anywhere in these tables.
-- Nothing reads or writes them until RFQ_ENABLED=true on the backend.
-- Requires 2026-10-23_suppliers.sql (foreign key to suppliers).
BEGIN;

CREATE SEQUENCE IF NOT EXISTS public.rfq_number_seq START 1;

CREATE TABLE IF NOT EXISTS public.rfqs (
    id              bigserial PRIMARY KEY,
    rfq_number      bigint      NOT NULL DEFAULT nextval('public.rfq_number_seq') UNIQUE,   -- label RFQ-0001
    supplier_id     bigint      NOT NULL REFERENCES public.suppliers(id) ON DELETE RESTRICT,
    -- Vendor info is a snapshot of the supplier taken when the RFQ is saved, so later supplier edits do not rewrite it.
    vendor_name     text        NOT NULL,
    vendor_contact  text,
    vendor_email    text,
    vendor_phone    text,
    vendor_address  text,
    vendor_tax_id   text,
    title           text        NOT NULL DEFAULT 'Solicitud de cotización',
    rfq_date        date        NOT NULL DEFAULT CURRENT_DATE,
    bill_to         text,
    payment_terms   text,
    notes           text,
    status          text        NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft', 'Sent', 'Converted')),
    created_by      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rfqs_supplier_idx ON public.rfqs (supplier_id);
CREATE INDEX IF NOT EXISTS rfqs_created_idx  ON public.rfqs (created_at DESC);

CREATE TABLE IF NOT EXISTS public.rfq_items (
    id           bigserial PRIMARY KEY,
    rfq_id       bigint  NOT NULL REFERENCES public.rfqs(id) ON DELETE CASCADE,
    position     integer NOT NULL,
    product_id   bigint  REFERENCES public.products(id) ON DELETE SET NULL,   -- where the line started; informational
    item         text    NOT NULL CHECK (btrim(item) <> ''),
    description  text,
    quantity     numeric(14,4) NOT NULL CHECK (quantity > 0),
    unit         text
);
CREATE INDEX IF NOT EXISTS rfq_items_rfq_idx ON public.rfq_items (rfq_id, position);

ALTER TABLE public.rfqs      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rfq_items ENABLE ROW LEVEL SECURITY;

COMMIT;
