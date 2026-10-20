-- Rollback for 2026-10-20_company_seal.sql.
-- Safe at any time: no other table references company_settings, and PDFs never print a seal
-- unless a request asks for it. Redeploy the previous backend first, or the seal endpoints return errors.

BEGIN;

DROP TABLE IF EXISTS public.company_settings;

-- Remove the uploaded seal and the bucket (the object must go first). Skipped where storage does not exist.
DO $$
BEGIN
    IF to_regclass('storage.objects') IS NOT NULL THEN
        DELETE FROM storage.objects WHERE bucket_id = 'company-seals';
        DELETE FROM storage.buckets WHERE id = 'company-seals';
    END IF;
END $$;

COMMIT;
