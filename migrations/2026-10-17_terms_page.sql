-- Phase 2, module 4: Terms and Conditions final page for quote and invoice PDFs. Additive.
-- One row (id = 1). No row = page OFF for both document types, starter text in terms_page/defaults.py.
CREATE TABLE IF NOT EXISTS terms_settings (
    id              smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    enabled_quote   boolean NOT NULL DEFAULT false,
    enabled_invoice boolean NOT NULL DEFAULT false,
    sections        jsonb   NOT NULL DEFAULT '{}'::jsonb,
    updated_at      timestamptz NOT NULL DEFAULT now(),
    updated_by      text
);
