-- 5 dummy suppliers for testing (P2). Run AFTER 2026-10-23_suppliers.sql. Safe to re-run.
-- Fake names and fake RNC values. Remove at go-live: DELETE FROM public.suppliers WHERE is_dummy;
BEGIN;
INSERT INTO public.suppliers (company_name, contact_name, email, phone, address, tax_id, notes, is_dummy) VALUES
 ('[PRUEBA] Aceros del Caribe SRL',   'Juan Pérez',     'prueba.aceros@example.com',    '809-555-0101', 'Av. Industrial 100, Santo Domingo', 'PRUEBA-0001', 'Proveedor de prueba: acero estructural', true),
 ('[PRUEBA] Tornillería Dominicana',  'María Santos',   'prueba.tornilleria@example.com','809-555-0102', 'Calle Duarte 45, Santiago',          'PRUEBA-0002', 'Proveedor de prueba: pernos y anclajes', true),
 ('[PRUEBA] Pinturas y Recubrimientos','Carlos Núñez',  'prueba.pinturas@example.com',  '809-555-0103', 'Zona Franca Itabo, Haina',          'PRUEBA-0003', 'Proveedor de prueba: pintura industrial', true),
 ('[PRUEBA] Techos y Paneles del Este','Ana Rodríguez', 'prueba.techos@example.com',    '829-555-0104', 'Carretera Mella km 8, SDE',         'PRUEBA-0004', 'Proveedor de prueba: láminas y paneles', true),
 ('[PRUEBA] Equipos y Herramientas RD','Luis Martínez', 'prueba.equipos@example.com',   '849-555-0105', 'Av. 27 de Febrero 300, Santo Domingo','PRUEBA-0005', 'Proveedor de prueba: herramientas', true)
ON CONFLICT DO NOTHING;
COMMIT;
