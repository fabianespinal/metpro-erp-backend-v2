-- ============================================================
-- Module F: unguessable public quote links
-- Target:   Supabase PostgreSQL (public schema)
-- Requires: PostgreSQL 13+ (gen_random_uuid() is built in)
-- Status:   NOT APPLIED. Run only after explicit approval.
-- Safe to re-run: every step is idempotent.
-- ============================================================

BEGIN;

ALTER TABLE quotes
    ADD COLUMN IF NOT EXISTS public_token uuid DEFAULT gen_random_uuid();

UPDATE quotes
SET public_token = gen_random_uuid()
WHERE public_token IS NULL;

ALTER TABLE quotes
    ALTER COLUMN public_token SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS quotes_public_token_key
    ON quotes (public_token);

COMMIT;

-- Verification (read-only). Expect: with_token = total = distinct_tokens.
-- SELECT COUNT(*) AS total,
--        COUNT(public_token) AS with_token,
--        COUNT(DISTINCT public_token) AS distinct_tokens
-- FROM quotes;
