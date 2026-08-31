ALTER TABLE catalog.sucursales
    ADD COLUMN IF NOT EXISTS razon_social text,
    ADD COLUMN IF NOT EXISTS rfc text,
    ADD COLUMN IF NOT EXISTS aliases text[] NOT NULL DEFAULT '{}';

ALTER TABLE core.facturas
    ADD COLUMN IF NOT EXISTS sucursal_origen text NOT NULL DEFAULT 'carga_manual',
    ADD COLUMN IF NOT EXISTS sucursal_deteccion jsonb;

CREATE UNIQUE INDEX IF NOT EXISTS sucursales_rfc_unico
    ON catalog.sucursales (rfc) WHERE rfc IS NOT NULL;

INSERT INTO catalog.sucursales (
    clave, nombre, restaurante, razon_social, rfc, aliases, activa
) VALUES (
    'DEMO-A',
    'RESTAURANTE DEMO UNO',
    'RESTAURANTE DEMO UNO',
    'RESTAURANTE DEMO UNO S.A. DE C.V.',
    'DEM010101AA1',
    ARRAY['DEMO-A', 'RESTAURANTE DEMO UNO', 'RESTAURANTE DEMO UNO', 'RESTAURANTE DEMO UNO'],
    true
)
ON CONFLICT (clave) DO UPDATE SET
    nombre = EXCLUDED.nombre,
    restaurante = EXCLUDED.restaurante,
    razon_social = EXCLUDED.razon_social,
    rfc = EXCLUDED.rfc,
    aliases = EXCLUDED.aliases,
    activa = true;

UPDATE core.facturas f
SET sucursal_id = s.id,
    sucursal_origen = 'reconocimiento_automatico',
    sucursal_deteccion = jsonb_build_object(
        'regla', 'migracion-demo-a-v1',
        'rfc', s.rfc,
        'razon_social', s.razon_social
    ),
    actualizada_en = now()
FROM catalog.sucursales s
WHERE s.clave = 'DEMO-A'
  AND f.estado NOT IN ('aprobada', 'rechazada')
  AND EXISTS (
      SELECT 1
      FROM ocr.resultados o
      WHERE o.factura_id = f.id
        AND (
            upper(o.texto_raw) LIKE '%DEM010101AA1%'
            OR upper(o.texto_raw) LIKE '%RESTAURANTE DEMO UNO%'
            OR upper(o.texto_raw) LIKE '%RESTAURANTE DEMO UNO%'
        )
  );
