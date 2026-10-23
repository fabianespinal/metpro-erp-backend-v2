-- Status history (S1, 2026-10-23). Additive only. One new table, nothing else changes.
-- Every quote and invoice status change is one row: who, when, from, to.
-- Append-only (trigger). RLS on, same posture as the other public tables.
-- Nothing reads or writes this table until STATUS_HISTORY_ENABLED=true on the backend.
BEGIN;

CREATE TABLE IF NOT EXISTS public.status_history (
    id             bigserial PRIMARY KEY,
    entity_type    text        NOT NULL CHECK (entity_type IN ('quote', 'invoice')),
    entity_key     text        NOT NULL,            -- quotes.quote_id, or invoices.id as text
    from_status    text,                            -- NULL = creation
    to_status      text        NOT NULL,
    actor_user_id  uuid        REFERENCES public.users(id) ON DELETE SET NULL,
    actor_name     text,                            -- name at the time of the change (survives user edits)
    changed_at     timestamptz NOT NULL DEFAULT now(),
    note           text
);
CREATE INDEX IF NOT EXISTS status_history_entity_idx
    ON public.status_history (entity_type, entity_key, changed_at DESC, id DESC);

ALTER TABLE public.status_history ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.status_history_block_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS status_history_append_only ON public.status_history;
CREATE TRIGGER status_history_append_only BEFORE UPDATE OR DELETE ON public.status_history
    FOR EACH ROW EXECUTE FUNCTION public.status_history_block_change();

COMMIT;
