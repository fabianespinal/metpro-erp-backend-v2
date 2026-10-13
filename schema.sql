-- ============================================================
-- METPRO ERP schema reference (PostgreSQL / Supabase)
--
-- Source: live column export (table_name, column_name, data_type),
--         uploaded 2026-10-13. Column names and types are LIVE.
--
-- NOT VERIFIED in this file (not in the export):
--   - primary keys, foreign keys, unique constraints, check constraints
--   - NOT NULL and DEFAULT values
--   - indexes
--   - full column list of `users` (export lists only `id`)
--
-- Those will be added from a full schema dump. Do not use this file to
-- create a new database until that dump is merged in.
--
-- Known live vs. old file differences:
--   quotes.included_charges   TEXT (old file: JSONB)
--   quotes.total_amount       DOUBLE PRECISION (old: NUMERIC(12,2))
--   quote_items.quantity/unit_price/discount_value  DOUBLE PRECISION (old: NUMERIC)
--   invoices table            has grand_total, subtotal, itbis_total, etc.
--                             (not in old file); old `quote_id UNIQUE` not verified
--   clients                   has NO created_at (old file: created_at)
--   products                  has NO created_at/updated_at (old file: both)
--   expenses                  has NO client_id; has client_name
--   invoice_items.id          UUID
--   users.id                  UUID (old file: SERIAL)
--   invoices.public_token     NOT PRESENT until migration
--                             migrations/2026-10-13_invoice_public_token.sql
-- ============================================================

-- clients
CREATE TABLE IF NOT EXISTS clients (
    -- constraints unverified
    id bigint,
    company_name text,
    contact_name text,
    email text,
    phone text,
    address text,
    tax_id text,
    notes text,
    updated_at timestamp with time zone
);

-- conduces
CREATE TABLE IF NOT EXISTS conduces (
    -- constraints unverified
    id uuid,
    conduce_number text,
    created_at timestamp with time zone,
    invoice_id bigint
);

-- contacts
CREATE TABLE IF NOT EXISTS contacts (
    -- constraints unverified
    id integer,
    company_id integer,
    name text,
    email text,
    phone text,
    created_at timestamp without time zone
);

-- expenses
CREATE TABLE IF NOT EXISTS expenses (
    -- constraints unverified
    expense_id integer,
    date date,
    category text,
    description text,
    amount numeric,
    payment_method text,
    project_id text,
    quote_id text,
    created_at timestamp without time zone,
    client_name text
);

-- invoice_items
CREATE TABLE IF NOT EXISTS invoice_items (
    -- constraints unverified
    id uuid,
    description text,
    quantity numeric,
    unit_price numeric,
    discount numeric,
    total numeric,
    invoice_id bigint,
    product_id bigint
);

-- invoice_payments
CREATE TABLE IF NOT EXISTS invoice_payments (
    -- constraints unverified
    id integer,
    invoice_id integer,
    amount numeric,
    payment_date date,
    method character varying,
    notes text
);

-- invoices
CREATE TABLE IF NOT EXISTS invoices (
    -- constraints unverified
    invoice_number text,
    quote_id text,
    status text,
    subtotal numeric,
    discount_total numeric,
    charges_total numeric,
    itbis_total numeric,
    grand_total numeric,
    notes text,
    created_at timestamp with time zone,
    updated_at timestamp with time zone,
    invoice_date timestamp with time zone,
    total_amount numeric,
    client_id bigint,
    id bigint,
    payment_terms text,
    valid_until date,
    amount_paid numeric,
    amount_due numeric,
    contact_id integer
);

-- products
CREATE TABLE IF NOT EXISTS products (
    -- constraints unverified
    id bigint,
    name text,
    description text,
    unit_price double precision
);

-- projects
CREATE TABLE IF NOT EXISTS projects (
    -- constraints unverified
    id integer,
    client_id integer,
    name text,
    description text,
    status text,
    start_date date,
    end_date date,
    estimated_budget numeric,
    notes text,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);

-- quote_items
CREATE TABLE IF NOT EXISTS quote_items (
    -- constraints unverified
    id bigint,
    quote_id text,
    product_name text,
    quantity double precision,
    unit_price double precision,
    discount_type text,
    discount_value double precision,
    product_id bigint
);

-- quotes
CREATE TABLE IF NOT EXISTS quotes (
    -- constraints unverified
    id bigint,
    quote_id text,
    client_id bigint,
    project_name text,
    total_amount double precision,
    status text,
    notes text,
    included_charges text,
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    payment_terms text,
    valid_until date,
    contact_id integer
);

-- users: export lists only id (uuid). Columns used by code and known to exist:
--   username, password_hash, email, full_name, role, is_active, created_at
-- Types and constraints unverified. Do not create from this block.
