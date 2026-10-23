-- Purchase orders (P3b, 2026-10-24). Additive only. Two new tables and one sequence; nothing existing changes.
-- DOP only, no tax. Prices are typed by hand from the supplier's pricing; nothing here reads product prices.
-- Nothing reads or writes these tables until PO_ENABLED=true on the backend (admin and superadmin only).
-- Requires 2026-10-23_suppliers.sql and 2026-10-24_rfq.sql.
BEGIN;

CREATE SEQUENCE IF NOT EXISTS public.po_number_seq START 1;

CREATE TABLE IF NOT EXISTS public.purchase_orders (
    id              bigserial PRIMARY KEY,
    po_number       bigint      NOT NULL DEFAULT nextval('public.po_number_seq') UNIQUE,   -- label PO-0001
    rfq_id          bigint      REFERENCES public.rfqs(id) ON DELETE SET NULL,             -- set when converted from an RFQ
    supplier_id     bigint      NOT NULL REFERENCES public.suppliers(id) ON DELETE RESTRICT,
    vendor_name     text        NOT NULL,
    vendor_contact  text,
    vendor_email    text,
    vendor_phone    text,
    vendor_address  text,
    vendor_tax_id   text,
    title           text        NOT NULL DEFAULT 'Orden de compra',
    po_date         date        NOT NULL DEFAULT CURRENT_DATE,
    bill_to         text,
    payment_terms   text,
    notes           text,
    status          text        NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft', 'Issued', 'Cancelled')),
    subtotal        numeric(16,2) NOT NULL DEFAULT 0 CHECK (subtotal >= 0),
    total           numeric(16,2) NOT NULL DEFAULT 0 CHECK (total >= 0),   -- no tax: equals subtotal
    created_by      text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS purchase_orders_supplier_idx ON public.purchase_orders (supplier_id);
CREATE INDEX IF NOT EXISTS purchase_orders_rfq_idx      ON public.purchase_orders (rfq_id);
CREATE INDEX IF NOT EXISTS purchase_orders_created_idx  ON public.purchase_orders (created_at DESC);

CREATE TABLE IF NOT EXISTS public.po_items (
    id           bigserial PRIMARY KEY,
    po_id        bigint  NOT NULL REFERENCES public.purchase_orders(id) ON DELETE CASCADE,
    position     integer NOT NULL,
    product_id   bigint  REFERENCES public.products(id) ON DELETE SET NULL,   -- informational
    item         text    NOT NULL CHECK (btrim(item) <> ''),
    description  text,
    quantity     numeric(14,4) NOT NULL CHECK (quantity > 0),
    unit         text,
    unit_price   numeric(14,4) NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
    amount       numeric(16,2) NOT NULL DEFAULT 0 CHECK (amount >= 0)       -- quantity x unit_price, rounded half up, by the backend
);
CREATE INDEX IF NOT EXISTS po_items_po_idx ON public.po_items (po_id, position);

ALTER TABLE public.purchase_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.po_items        ENABLE ROW LEVEL SECURITY;

COMMIT;
