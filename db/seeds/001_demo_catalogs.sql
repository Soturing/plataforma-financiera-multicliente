BEGIN;

INSERT INTO catalog.sucursales (clave, nombre, restaurante)
VALUES ('DEMO-01', 'Sucursal Demo', 'Restaurante Demo')
ON CONFLICT (clave) DO NOTHING;

INSERT INTO catalog.sucursales (clave, nombre, restaurante, razon_social, rfc, aliases)
VALUES (
    'DEMO-A', 'RESTAURANTE DEMO UNO', 'RESTAURANTE DEMO UNO', 'RESTAURANTE DEMO UNO S.A. DE C.V.',
    'DEM010101AA1', ARRAY['DEMO-A', 'RESTAURANTE DEMO UNO', 'RESTAURANTE DEMO UNO', 'RESTAURANTE DEMO UNO']
)
ON CONFLICT (clave) DO UPDATE SET
    nombre = EXCLUDED.nombre, restaurante = EXCLUDED.restaurante,
    razon_social = EXCLUDED.razon_social, rfc = EXCLUDED.rfc, aliases = EXCLUDED.aliases;

INSERT INTO catalog.categorias (clave, nombre, orden)
VALUES
    ('FIJOS', 'Fijos', 10),
    ('VARIABLES', 'Variables', 20),
    ('BARRA', 'Barra', 30),
    ('RESTAURANTE', 'Restaurante', 40)
ON CONFLICT (clave) DO NOTHING;

INSERT INTO catalog.subcategorias (categoria_id, clave, nombre)
SELECT id, 'RENTA', 'Renta' FROM catalog.categorias WHERE clave = 'FIJOS'
ON CONFLICT (categoria_id, clave) DO NOTHING;

INSERT INTO catalog.subcategorias (categoria_id, clave, nombre)
SELECT id, 'MANTENIMIENTO', 'Mantenimiento' FROM catalog.categorias WHERE clave = 'VARIABLES'
ON CONFLICT (categoria_id, clave) DO NOTHING;

INSERT INTO catalog.centros_costo (clave, nombre)
VALUES
    ('COCINA', 'Cocina'),
    ('BARRA', 'Barra'),
    ('GENERAL', 'General')
ON CONFLICT (clave) DO NOTHING;

INSERT INTO catalog.proveedores (rfc, nombre_legal, nombre_normalizado)
VALUES (NULL, 'Proveedor Ficticio Base', 'Proveedor Ficticio Base')
ON CONFLICT DO NOTHING;

COMMIT;
