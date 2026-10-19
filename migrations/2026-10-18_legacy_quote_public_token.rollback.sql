-- Rollback X-07: remove the token added to Q-10002 (its link stops working).
UPDATE public.quotes SET public_token = NULL WHERE quote_number = 10002;
