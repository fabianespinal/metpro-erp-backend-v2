-- METPRO Engineering Estimate: activate Nave Industrial version 1.0 (I5 step 4).
-- Approvals recorded 2026-10-23: Q-E3-2 yes (E54 = W10x12), Q-E3-3 DOP, Q-E3-6 keep (no stored default per role).
-- ONE-WAY: after this, profiles, constants and materials of version 1.0 are frozen (trigger). Changes need a new version.
-- Does NOT switch the estimator on. ENGINEERING_ESTIMATE_ENABLED stays unset.
BEGIN;
UPDATE public.estimator_versions v
SET status = 'active',
    activated_at = now(),
    notes = v.notes || ' | Currency: DOP (RD$) confirmed by Fabian 2026-10-23. E54 = W10x12 confirmed (Q-E3-2). Constants D5, D6, D10, D17-D19, D28 carried as in the workbook, meaning unconfirmed.'
FROM public.estimator_models m
WHERE v.model_id = m.id AND m.name = 'Nave Industrial' AND v.version = '1.0' AND v.status = 'draft';
-- Must report exactly 1 row: version 1.0 active.
SELECT v.id, v.version, v.status, v.activated_at FROM public.estimator_versions v JOIN public.estimator_models m ON m.id = v.model_id WHERE m.name = 'Nave Industrial' AND v.status = 'active';
COMMIT;
