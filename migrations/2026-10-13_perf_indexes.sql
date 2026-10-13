-- ============================================================
-- Module E: indexes on filter, join, and ORDER BY columns
-- Target:   Supabase PostgreSQL (public schema)
-- Status:   NOT APPLIED. Run only after explicit approval.
--
-- Idempotent. For each (table, column):
--   creates idx_<table>_<column> only if NO existing index already
--   leads with that column. Existing indexes are never duplicated.
--
-- Note: CREATE INDEX (not CONCURRENTLY) takes a SHARE lock and blocks
-- writes on that table while it runs. Tables are small; expect seconds.
-- ============================================================

DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT * FROM (VALUES
            ('quote_items',      'quote_id'),
            ('invoice_items',    'invoice_id'),
            ('invoice_payments', 'invoice_id'),
            ('conduces',         'invoice_id'),
            ('invoices',         'client_id'),
            ('invoices',         'contact_id'),
            ('invoices',         'status'),
            ('invoices',         'invoice_date'),
            ('quotes',           'client_id'),
            ('quotes',           'contact_id'),
            ('quotes',           'status'),
            ('quotes',           'created_at'),
            ('contacts',         'company_id'),
            ('expenses',         'created_at'),
            ('projects',         'client_id'),
            ('projects',         'created_at')
        ) AS t(tbl, col)
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_index ix
            JOIN pg_class ct ON ct.oid = ix.indrelid
            JOIN pg_attribute a ON a.attrelid = ct.oid AND a.attnum = ix.indkey[0]
            WHERE ct.relname = r.tbl
              AND a.attname  = r.col
        ) THEN
            EXECUTE format(
                'CREATE INDEX IF NOT EXISTS %I ON %I (%I)',
                'idx_' || r.tbl || '_' || r.col, r.tbl, r.col
            );
            RAISE NOTICE 'created index on %.%', r.tbl, r.col;
        ELSE
            RAISE NOTICE 'skipped %.% (already indexed)', r.tbl, r.col;
        END IF;
    END LOOP;
END $$;

-- Verification (read-only): list every index on the target tables.
-- SELECT tablename, indexname, indexdef
-- FROM pg_indexes
-- WHERE schemaname = 'public'
--   AND tablename IN ('quote_items','invoice_items','invoice_payments','conduces',
--                     'invoices','quotes','contacts','expenses','projects')
-- ORDER BY tablename, indexname;
