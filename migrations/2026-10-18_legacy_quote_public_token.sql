-- Debug X-07: finalized quotes created before public links existed get a token, so they can be
-- sent and opened on metprord.site. Production: Q-10002 (Approved). Drafts keep NULL by design.
UPDATE public.quotes SET public_token = gen_random_uuid()
WHERE public_token IS NULL AND status IN ('Final', 'Sent', 'Approved', 'Invoiced', 'Rejected');
