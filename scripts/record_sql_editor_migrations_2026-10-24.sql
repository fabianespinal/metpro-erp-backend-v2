-- Audit H5 (2026-10-24): record in the Supabase migration log the changes that were applied in the SQL editor.
-- METADATA ONLY. Touches supabase_migrations.schema_migrations; no application table changes.
-- Run once, after approval, in the Supabase SQL editor. Re-running is harmless (ON CONFLICT DO NOTHING).
-- Each row points at the repository file that holds the exact SQL that was applied.
BEGIN;
INSERT INTO supabase_migrations.schema_migrations (version, name, created_by)
VALUES
    ('20261022235010', '2026_10_22_product_dimensions (repo: migrations/2026-10-22_product_dimensions.sql)', 'sql-editor-backfill'),
    ('20261022235015', '2026_10_22_payment_immutability (repo: migrations/2026-10-22_payment_immutability.sql)', 'sql-editor-backfill'),
    ('20261023141300', '2026_10_22_estimator_schema (repo: migrations/2026-10-22_estimator_schema.sql)', 'sql-editor-backfill'),
    ('20261023141301', '2026_10_22_estimator_seed_v1 (repo: migrations/2026-10-22_estimator_seed_v1.sql)', 'sql-editor-backfill'),
    ('20261023141302', '2026_10_22_estimator_run_idempotency (repo: migrations/2026-10-22_estimator_run_idempotency.sql)', 'sql-editor-backfill'),
    ('20261023142651', '2026_10_23_estimator_activate_v1 (repo: migrations/2026-10-23_estimator_activate_v1.sql)', 'sql-editor-backfill'),
    ('20261023150000', '2026_10_23_pdf_medidas_print_items (repo: migrations/2026-10-23_pdf_medidas_print_items.sql)', 'sql-editor-backfill'),
    ('20261023163000', '2026_10_23_status_history (repo: migrations/2026-10-23_status_history.sql)', 'sql-editor-backfill')
ON CONFLICT (version) DO NOTHING;
-- Expect 8 rows with created_by = 'sql-editor-backfill'.
SELECT version, name FROM supabase_migrations.schema_migrations WHERE created_by = 'sql-editor-backfill' ORDER BY version;
COMMIT;
