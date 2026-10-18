-- Rollback for 2026-10-18_catalog_cleanup.sql: original values captured before the change.
BEGIN;
UPDATE products SET name = 'Mesa de acero inoxidable simple en Area de coccion' WHERE id = 51;
UPDATE products SET name = 'Tramera de Acero Inoxidable' WHERE id = 129;
UPDATE products SET name = 'SUMINISTRO DE TORNILLOS 3/4x 3 PARA METALDECK' WHERE id = 77;
UPDATE products SET name = 'ANGULAR ACERO 2? x 2? DE 1/4' WHERE id = 17;
UPDATE products SET name = 'AISLANTE DE 3/4?' WHERE id = 138;
UPDATE products SET description = 'con Z' || chr(65533) || 'calo h:10cm 1.20m x 0.85m x 0.70m  / ACERO INOXIDABLE AISI 304' WHERE id = 48;
UPDATE products SET description = 'con Z' || chr(65533) || 'calo h:10cm / ACERO INOXIDABLE AISI 304 / 1.50m x 0.85m x 0.70m' WHERE id = 49;
INSERT INTO products (id, name, description, unit_price) VALUES
 (140, 'BA' || chr(65533) || 'OS Y AGUAS PLUVIALES', '', 0.00),
 (142, 'DISE' || chr(65533) || 'OS DE PLANOS ESTRUCTURALES, SANITARIOS Y ELECTRICOS', '', 0.00),
 (156, 'Viga de Acero Inoxidable', 'Viga de Acero Inoxidable', 220.00),
 (147, 'Mesa de acero inoxidable simple en Area de cocci' || chr(65533) || 'n', '1.10m x 0.85m x 1.00m  / ACERO INOXIDABLE AISI 304', 20.00),
 (152, 'Tramer' || chr(65533) || 'a de Acero Inoxidable', '1.20x0.42x1.76 / ACERO INOXIDABLE AISI 304 / 1.20m x 1.76m x 0.42m', 125.00),
 (149, 'SUMINISTRO DE TORNILLOS 3/4?x 3? PARA METALDECK', '', 90.00),
 (139, 'ANGULAR ACERO 2? x 2? DE 1/4?', 'ANGULAR', 2258.52)
ON CONFLICT (id) DO NOTHING;
COMMIT;
