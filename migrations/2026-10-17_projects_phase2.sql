-- Phase 2, module 1: projects created from approved quotes. Additive.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS quote_id text REFERENCES quotes(quote_id) ON DELETE SET NULL;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS quote_number bigint;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS job_site_address text;
-- One project per quote.
CREATE UNIQUE INDEX IF NOT EXISTS projects_quote_id_key ON projects (quote_id) WHERE quote_id IS NOT NULL;
-- "pending" is the initial status ("Pendiente"). on_hold and cancelled were already used by the UI.
ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_status_check;
ALTER TABLE projects ADD CONSTRAINT projects_status_check
  CHECK (status = ANY (ARRAY['pending','planning','in_progress','completed','on_hold','cancelled']));
