BEGIN;

INSERT INTO catalog.sucursales (
    clave, nombre, restaurante, razon_social, rfc, aliases, activa
) VALUES
    (
        'DEMO-A', 'RESTAURANTE DEMO UNO', 'RESTAURANTE DEMO UNO',
        'RESTAURANTE DEMO UNO S.A. DE C.V.', 'DEM010101AA1',
        ARRAY['DEMO-A', 'RESTAURANTE DEMO UNO', 'RESTAURANTE DEMO UNO', 'RESTAURANTE DEMO UNO'], true
    ),
    (
        'DEMO-B', 'DEMO-B', 'RESTAURANTE DEMO DOS',
        'RESTAURANTE DEMO DOS S.A. DE C.V.', 'DEM010101BB2',
        ARRAY['BGR', 'DEMO-B', 'RESTAURANTE DEMO DOS', 'RESTAURANTE DEMO DOS', 'RESTAURANTE DEMO DOS S.A. DE C.V.'], true
    ),
    (
        'DEMO-C', 'RESTAURANTE DEMO TRES', 'RESTAURANTE DEMO TRES',
        'RESTAURANTE DEMO TRES S.A. DE C.V.', 'DEM010101CC3',
        ARRAY['DEMO-C', 'RESTAURANTE DEMO TRES', 'SUCURSAL DEMO TRES'], true
    )
ON CONFLICT (clave) DO UPDATE SET
    nombre = EXCLUDED.nombre,
    restaurante = EXCLUDED.restaurante,
    razon_social = EXCLUDED.razon_social,
    rfc = EXCLUDED.rfc,
    aliases = EXCLUDED.aliases,
    activa = true;

-- POR-ASIGNAR permanece activa como bandeja técnica de CEDIS, no como restaurante.
UPDATE catalog.sucursales
SET activa = false
WHERE clave NOT IN ('DEMO-A', 'DEMO-B', 'DEMO-C', 'POR-ASIGNAR');

-- Los movimientos y parámetros ficticios dejan de participar en el consolidado.
DELETE FROM finance.ventas v
USING catalog.sucursales s
WHERE s.id = v.sucursal_id
  AND s.clave = 'DEMO-01';

DELETE FROM finance.parametros_equilibrio p
USING catalog.sucursales s
WHERE s.id = p.sucursal_id
  AND s.clave = 'DEMO-01';

COMMIT;
