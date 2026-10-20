-- 2026-10-20: company seal (sello) for printed PDFs. Additive only.
-- Rollback: 2026-10-20_company_seal.rollback.sql
--
-- One row (id = 1), same pattern as terms_settings.
--   seal_image_url           object path inside the private bucket company-seals ("metpro/seal.png"). NULL = no seal uploaded.
--   seal_enabled_by_default  pre-checks "Imprimir sello" in the document dialogs. Never prints a seal by itself.
-- The seal is only printed when a request asks for it (print_seal=true). Nothing is stored per document.

BEGIN;

CREATE TABLE IF NOT EXISTS public.company_settings (
    id smallint NOT NULL DEFAULT 1,
    seal_image_url text,
    seal_enabled_by_default boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text,
    CONSTRAINT company_settings_pkey PRIMARY KEY (id),
    CONSTRAINT company_settings_id_check CHECK (id = 1)
);

INSERT INTO public.company_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Same posture as the other tables: RLS on, no policies. The backend connects as owner.
ALTER TABLE public.company_settings ENABLE ROW LEVEL SECURITY;

-- Private bucket for the seal. Skipped where the Supabase storage schema does not exist (CI, local replica).
DO $$
BEGIN
    IF to_regclass('storage.buckets') IS NOT NULL THEN
        INSERT INTO storage.buckets (id, name, public) VALUES ('company-seals', 'company-seals', false)
        ON CONFLICT (id) DO NOTHING;
    END IF;
END $$;

COMMIT;
