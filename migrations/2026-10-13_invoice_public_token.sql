-- ============================================================
-- Module B: unguessable public invoice links
-- Target:   Supabase PostgreSQL (public schema)
-- Requires: PostgreSQL 13+ (gen_random_uuid() is built in)
-- Status:   APPLIED to production. Effects verified 2026-10-15 by read-only
--           schema and ACL checks. Apply timestamp unknown; migration history
--           not recoverable.
-- Safe to re-run: every step is idempotent.
-- ============================================================

BEGIN;

-- 1. Add column. Volatile default fills every existing row with its own UUID.
ALTER TABLE invoices
    ADD COLUMN IF NOT EXISTS public_token uuid DEFAULT gen_random_uuid();

-- 2. Backfill any row that somehow has NULL (defensive).
UPDATE invoices
SET public_token = gen_random_uuid()
WHERE public_token IS NULL;

-- 3. Enforce presence and uniqueness.
ALTER TABLE invoices
    ALTER COLUMN public_token SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS invoices_public_token_key
    ON invoices (public_token);

COMMIT;

-- ============================================================
-- Verification (read-only). Expect: null_count = 0, distinct = total.
-- ============================================================
-- SELECT COUNT(*) AS total,
--        COUNT(public_token) AS with_token,
--        COUNT(DISTINCT public_token) AS distinct_tokens
-- FROM invoices;
