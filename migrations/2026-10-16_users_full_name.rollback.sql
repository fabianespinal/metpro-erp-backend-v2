-- Rollback for 2026-10-16_users_full_name.sql. NOT APPLIED.
-- Drops the column. Any full_name values stored after apply are lost.

ALTER TABLE public.users DROP COLUMN IF EXISTS full_name;
