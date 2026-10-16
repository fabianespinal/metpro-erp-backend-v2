-- 2026-10-16: add users.full_name (code already reads and writes it).
-- APPLIED to production 2026-10-16 (column confirmed: text, nullable, no default).
-- Rollback: migrations/2026-10-16_users_full_name.rollback.sql

ALTER TABLE public.users ADD COLUMN IF NOT EXISTS full_name text;
