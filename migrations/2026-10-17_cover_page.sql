-- Phase 2, module 3: editable cover page text for quote and invoice PDFs. Additive.
-- No row = built-in default text (cover_page/defaults.py). enabled=false hides the cover.
CREATE TABLE IF NOT EXISTS cover_page_templates (
    doc_type   text PRIMARY KEY CHECK (doc_type IN ('quote', 'invoice')),
    body       text NOT NULL,
    enabled    boolean NOT NULL DEFAULT true,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text
);
