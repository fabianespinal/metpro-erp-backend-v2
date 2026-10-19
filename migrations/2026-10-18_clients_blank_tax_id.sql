-- Debug B-21 (approved 2026-10-18): an empty RNC is stored as NULL, not ''.
-- Production before: 44 rows (ids 12..55, from an earlier CSV import). No visible change in the UI.
UPDATE public.clients SET tax_id = NULL WHERE tax_id = '';
