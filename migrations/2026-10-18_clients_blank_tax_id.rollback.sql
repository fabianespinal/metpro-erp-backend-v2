-- Rollback B-21 data cleanup: restore '' on exactly the rows changed (ids captured 2026-10-18).
UPDATE public.clients SET tax_id = ''
WHERE tax_id IS NULL
  AND id IN (12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55);
