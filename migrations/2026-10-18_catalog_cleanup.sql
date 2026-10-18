-- 2026-10-18: product catalog cleanup (approved by Fabian). Data only, no schema change.
-- Garbled names came from an old non-UTF-8 import ("?" was the inch mark; U+FFFD replaced accents).
-- Deletes only rows with no template pack, quote item or invoice item reference.
BEGIN;
UPDATE products SET name = 'Mesa de acero inoxidable simple en Área de cocción' WHERE id = 51;
UPDATE products SET name = 'Tramería de Acero Inoxidable' WHERE id = 129;
UPDATE products SET name = 'SUMINISTRO DE TORNILLOS 3/4" x 3" PARA METALDECK' WHERE id = 77;
UPDATE products SET name = 'ANGULAR ACERO 2" x 2" DE 1/4"' WHERE id = 17;
UPDATE products SET name = 'AISLANTE DE 3/4"' WHERE id = 138;
UPDATE products SET description = replace(description, chr(65533), 'ó') WHERE id IN (48, 49);
DELETE FROM products p
 WHERE p.id IN (140, 142, 156, 147, 152, 149, 139)
   AND NOT EXISTS (SELECT 1 FROM template_pack_items t WHERE t.product_id = p.id)
   AND NOT EXISTS (SELECT 1 FROM quote_items q WHERE q.product_id = p.id)
   AND NOT EXISTS (SELECT 1 FROM invoice_items i WHERE i.product_id = p.id);
COMMIT;
