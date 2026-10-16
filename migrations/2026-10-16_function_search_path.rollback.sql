BEGIN;
ALTER FUNCTION public.update_updated_at_column() RESET search_path;
ALTER FUNCTION public.update_timestamp() RESET search_path;
COMMIT;
