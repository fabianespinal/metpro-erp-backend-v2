UPDATE projects SET status = 'planning' WHERE status IN ('pending','on_hold','cancelled');
ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_status_check;
ALTER TABLE projects ADD CONSTRAINT projects_status_check
  CHECK (status = ANY (ARRAY['planning','in_progress','completed']));
DROP INDEX IF EXISTS projects_quote_id_key;
ALTER TABLE projects DROP COLUMN IF EXISTS job_site_address;
ALTER TABLE projects DROP COLUMN IF EXISTS quote_number;
ALTER TABLE projects DROP COLUMN IF EXISTS quote_id;
