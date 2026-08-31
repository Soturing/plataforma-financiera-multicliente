\set ON_ERROR_STOP on

BEGIN;

WITH nueva AS (
    INSERT INTO core.facturas (
        sucursal_id, archivo_url, archivo_nombre, archivo_mime,
        archivo_sha256, creada_por
    )
    SELECT
        id, 'demo://factura-sigma.jpg', 'factura-sigma.jpg', 'image/jpeg',
        repeat('a', 64), 'smoke-test'
    FROM catalog.sucursales
    WHERE clave = 'DEMO-01'
    RETURNING id
), resultado_ocr AS (
    INSERT INTO ocr.resultados (
        factura_id, version, proveedor_ocr, modelo_ocr,
        texto_raw, json_raw, confianza
    )
    SELECT
        id, 1, 'simulado', 'demo-v0',
        'PROVEEDOR FICTICIO BASE SUBTOTAL 10000 IVA 1600 TOTAL 11600',
        '{"subtotal":10000,"iva":1600,"total":11600}'::jsonb,
        0.98
    FROM nueva
    RETURNING id, factura_id
), interpretacion AS (
    INSERT INTO ai.interpretaciones (
        factura_id, ocr_resultado_id, version, modelo_ia, reglas_version,
        proveedor_id, proveedor_propuesto, fecha_emision,
        subtotal, iva, total, categoria_id, subcategoria_id,
        centro_costo_id, confianza, salida_json
    )
    SELECT
        ro.factura_id, ro.id, 1, 'simulado', '0.1',
        p.id, p.nombre_normalizado, DATE '2026-08-07',
        10000, 1600, 11600, c.id, NULL,
        cc.id, 0.97,
        '{"proveedor":"Proveedor Ficticio Base","subtotal":10000,"iva":1600,"total":11600}'::jsonb
    FROM resultado_ocr ro
    CROSS JOIN catalog.proveedores p
    CROSS JOIN catalog.categorias c
    CROSS JOIN catalog.centros_costo cc
    WHERE p.nombre_normalizado = 'Proveedor Ficticio Base'
      AND c.clave = 'RESTAURANTE'
      AND cc.clave = 'COCINA'
    RETURNING id, factura_id, proveedor_id, categoria_id, subcategoria_id, centro_costo_id
), validacion AS (
    INSERT INTO core.validaciones (
        factura_id, interpretacion_id, codigo, severidad,
        aprobada, campo, mensaje
    )
    SELECT
        factura_id, id, 'CUADRE_TOTAL', 'informativa', true,
        'total', 'Subtotal más IVA coincide con el total'
    FROM interpretacion
    RETURNING factura_id, interpretacion_id
), revision AS (
    INSERT INTO core.revisiones (
        factura_id, interpretacion_id, decision, revisada_por
    )
    SELECT
        factura_id, interpretacion_id, 'aprobada', 'smoke-test'
    FROM validacion
    RETURNING id, factura_id, interpretacion_id
), final AS (
    INSERT INTO core.facturas_finales (
        factura_id, revision_id, interpretacion_id, sucursal_id,
        proveedor_id, fecha_emision, subtotal, iva, total,
        categoria_id, subcategoria_id, centro_costo_id, aprobada_por
    )
    SELECT
        r.factura_id, r.id, r.interpretacion_id, s.id,
        i.proveedor_id, DATE '2026-08-07', 10000, 1600, 11600,
        i.categoria_id, i.subcategoria_id, i.centro_costo_id, 'smoke-test'
    FROM revision r
    JOIN interpretacion i ON i.id = r.interpretacion_id
    CROSS JOIN catalog.sucursales s
    WHERE s.clave = 'DEMO-01'
    RETURNING factura_id
)
SELECT count(*) AS facturas_finales_creadas FROM final;

UPDATE core.facturas
SET estado = 'aprobada', actualizada_en = now()
WHERE creada_por = 'smoke-test';

DO $$
DECLARE
    filas integer;
BEGIN
    SELECT count(*) INTO filas
    FROM analytics.facturas_consumo
    WHERE proveedor = 'Proveedor Ficticio Base'
      AND total = 11600.00
      AND semana_iso = 32;

    IF filas <> 1 THEN
        RAISE EXCEPTION 'Pipeline inválido: se esperaba 1 fila analytics y se encontraron %', filas;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM core.facturas
        WHERE creada_por = 'smoke-test' AND estado = 'aprobada'
    ) THEN
        RAISE EXCEPTION 'Pipeline inválido: la factura no terminó aprobada';
    END IF;
END $$;

ROLLBACK;

SELECT 'pipeline_smoke_ok' AS resultado;
