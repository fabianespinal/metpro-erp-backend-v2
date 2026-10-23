-- Engineering Estimate I1-a: data layer. Additive only. Nothing reads these tables until phase I3.
-- 7 tables + quotes.quote_type (nullable, no backfill: legacy quotes behave as standard).
-- RLS is enabled on every new table (same posture as the rest of public).
-- Draft versions are editable; once a version is not draft its child rows are frozen.
-- Runs and audit rows are append-only (enforced by trigger).
BEGIN;

CREATE TABLE IF NOT EXISTS public.estimator_models (
    id          bigserial PRIMARY KEY,
    name        text NOT NULL UNIQUE,
    rule_set    text NOT NULL,
    status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired')),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.estimator_versions (
    id             bigserial PRIMARY KEY,
    model_id       bigint NOT NULL REFERENCES public.estimator_models(id),
    version        text NOT NULL,
    rule_revision  integer NOT NULL,
    status         text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'retired')),
    notes          text,
    activated_by   uuid REFERENCES public.users(id),
    activated_at   timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (model_id, version),
    CHECK (status = 'draft' OR activated_at IS NOT NULL)
);
-- At most one active version per model.
CREATE UNIQUE INDEX IF NOT EXISTS estimator_versions_one_active
    ON public.estimator_versions (model_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS public.estimator_profiles (
    id                   bigserial PRIMARY KEY,
    version_id           bigint NOT NULL REFERENCES public.estimator_versions(id),
    designation          text NOT NULL,          -- canonical, for example W12x40
    display_designation  text NOT NULL,          -- as printed in the workbook
    family               text NOT NULL DEFAULT 'W',
    depth_in             numeric(8,2),
    lb_per_ft            numeric(10,4) NOT NULL CHECK (lb_per_ft > 0),
    status               text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    source_note          text,
    UNIQUE (version_id, designation)
);

CREATE TABLE IF NOT EXISTS public.estimator_constants (
    id            bigserial PRIMARY KEY,
    version_id    bigint NOT NULL REFERENCES public.estimator_versions(id),
    key           text NOT NULL,
    kind          text NOT NULL CHECK (kind IN ('constant', 'rate', 'default_quantity')),
    value         numeric(18,8) NOT NULL,
    unit          text,
    workbook_cell text,
    status        text NOT NULL CHECK (status IN ('documented', 'assumed', 'unexplained')),
    note          text,
    UNIQUE (version_id, key)
);

CREATE TABLE IF NOT EXISTS public.estimator_materials (
    id             bigserial PRIMARY KEY,
    version_id     bigint NOT NULL REFERENCES public.estimator_versions(id),
    row_ref        integer NOT NULL,             -- workbook row of the priced line
    sort_order     integer NOT NULL,
    category       text NOT NULL,
    description    text NOT NULL,
    unit_label     text NOT NULL,
    unit_basis     text,                         -- for PIE lines: ASSUMED linear foot
    driver_key     text,                         -- rule cell that gives the quantity, NULL when fixed
    fixed_quantity numeric(18,4),
    total_is_price boolean NOT NULL DEFAULT false,
    role_key       text,                         -- steel role for lines 78 to 82
    price          numeric(18,4) NOT NULL CHECK (price >= 0),
    product_id     bigint REFERENCES public.products(id),
    item_type      text NOT NULL DEFAULT 'product' CHECK (item_type IN ('product', 'service', 'custom')),
    print_on_pdf   boolean NOT NULL DEFAULT true,
    UNIQUE (version_id, row_ref),
    CHECK (driver_key IS NOT NULL OR fixed_quantity IS NOT NULL OR total_is_price)
);

CREATE TABLE IF NOT EXISTS public.estimator_runs (
    id            bigserial PRIMARY KEY,
    version_id    bigint NOT NULL REFERENCES public.estimator_versions(id),
    rule_revision integer NOT NULL,
    generated_by  uuid NOT NULL REFERENCES public.users(id),
    inputs        jsonb NOT NULL,
    snapshot      jsonb NOT NULL,                -- weights, constants and prices used
    results       jsonb NOT NULL,                -- lines and intermediates, unrounded
    warnings      jsonb NOT NULL DEFAULT '[]'::jsonb,
    overrides     jsonb NOT NULL DEFAULT '[]'::jsonb,   -- each with reason, user, timestamp
    quote_id      bigint REFERENCES public.quotes(id),
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.quote_edit_audit (
    id             bigserial PRIMARY KEY,
    quote_id       bigint NOT NULL REFERENCES public.quotes(id),
    quote_item_id  bigint,                       -- no FK: lines may be removed later
    field          text NOT NULL,
    old_value      text,
    new_value      text,
    reason         text NOT NULL CHECK (length(btrim(reason)) > 0),
    user_id        uuid NOT NULL REFERENCES public.users(id),
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS quote_edit_audit_quote_idx ON public.quote_edit_audit (quote_id);
CREATE INDEX IF NOT EXISTS estimator_runs_version_idx ON public.estimator_runs (version_id);

ALTER TABLE public.quotes ADD COLUMN IF NOT EXISTS quote_type text
    CHECK (quote_type IS NULL OR quote_type IN ('standard', 'template', 'engineering_estimate'));

-- Append-only: runs and audit rows never change.
CREATE OR REPLACE FUNCTION public.estimator_block_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS estimator_runs_append_only ON public.estimator_runs;
CREATE TRIGGER estimator_runs_append_only BEFORE UPDATE OR DELETE ON public.estimator_runs
    FOR EACH ROW EXECUTE FUNCTION public.estimator_block_change();
DROP TRIGGER IF EXISTS quote_edit_audit_append_only ON public.quote_edit_audit;
CREATE TRIGGER quote_edit_audit_append_only BEFORE UPDATE OR DELETE ON public.quote_edit_audit
    FOR EACH ROW EXECUTE FUNCTION public.estimator_block_change();

-- Frozen versions: no insert, update or delete on child rows unless the version is draft.
CREATE OR REPLACE FUNCTION public.estimator_freeze_children() RETURNS trigger AS $$
DECLARE
    vid bigint;
    vstatus text;
BEGIN
    vid := CASE WHEN TG_OP = 'DELETE' THEN OLD.version_id ELSE NEW.version_id END;
    SELECT status INTO vstatus FROM public.estimator_versions WHERE id = vid;
    IF vstatus IS DISTINCT FROM 'draft' THEN
        RAISE EXCEPTION 'estimator version % is % and cannot be edited; clone it instead', vid, vstatus;
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS estimator_profiles_freeze ON public.estimator_profiles;
CREATE TRIGGER estimator_profiles_freeze BEFORE INSERT OR UPDATE OR DELETE ON public.estimator_profiles
    FOR EACH ROW EXECUTE FUNCTION public.estimator_freeze_children();
DROP TRIGGER IF EXISTS estimator_constants_freeze ON public.estimator_constants;
CREATE TRIGGER estimator_constants_freeze BEFORE INSERT OR UPDATE OR DELETE ON public.estimator_constants
    FOR EACH ROW EXECUTE FUNCTION public.estimator_freeze_children();
DROP TRIGGER IF EXISTS estimator_materials_freeze ON public.estimator_materials;
CREATE TRIGGER estimator_materials_freeze BEFORE INSERT OR UPDATE OR DELETE ON public.estimator_materials
    FOR EACH ROW EXECUTE FUNCTION public.estimator_freeze_children();

ALTER TABLE public.estimator_models    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.estimator_versions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.estimator_profiles  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.estimator_constants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.estimator_materials ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.estimator_runs      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quote_edit_audit    ENABLE ROW LEVEL SECURITY;

COMMIT;
