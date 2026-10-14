-- ============================================================
-- Migration: request_logs table (item 12, module 1)
-- Date:      2026-10-14
-- Target:    Production Supabase, public schema
-- Idempotent: safe to re-run.
--
-- Effects:
--   - Creates public.request_logs. One row per logged request.
--   - Stores metadata only. Never request or response bodies.
--   - Enables RLS with no policies, matching the 2026-10-13 security
--     migration. The backend connects as the table owner and bypasses RLS.
--   - Index on timestamp supports the 90-day retention delete.
--
-- Pre-check (read only): SELECT to_regclass('public.request_logs');
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.request_logs (
    id               BIGSERIAL PRIMARY KEY,
    "timestamp"      TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_sub         TEXT,
    method           TEXT NOT NULL,
    path             TEXT NOT NULL,
    status_code      INTEGER NOT NULL,
    latency_ms       INTEGER NOT NULL,
    client_ip        TEXT,
    is_public        BOOLEAN NOT NULL DEFAULT FALSE,
    is_authenticated BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_request_logs_timestamp
    ON public.request_logs ("timestamp");

ALTER TABLE public.request_logs ENABLE ROW LEVEL SECURITY;

COMMIT;
