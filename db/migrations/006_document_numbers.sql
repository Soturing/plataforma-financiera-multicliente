ALTER TABLE ai.interpretaciones
    ADD COLUMN IF NOT EXISTS folio_origen text;

ALTER TABLE core.facturas_finales
    ADD COLUMN IF NOT EXISTS folio_origen text;

ALTER TABLE core.comprobantes_internos
    ADD COLUMN IF NOT EXISTS numero_documento text,
    ADD COLUMN IF NOT EXISTS numero_documento_origen text;

UPDATE ai.interpretaciones
SET folio = to_char(fecha_emision, 'DDMMYYYY'), folio_origen = 'fecha'
WHERE (folio IS NULL OR trim(folio) = '') AND fecha_emision IS NOT NULL;

UPDATE ai.interpretaciones
SET folio_origen = 'detectado'
WHERE folio IS NOT NULL AND folio_origen IS NULL;

UPDATE core.facturas_finales
SET folio = to_char(fecha_emision, 'DDMMYYYY'), folio_origen = 'fecha'
WHERE folio IS NULL OR trim(folio) = '';

UPDATE core.facturas_finales
SET folio_origen = 'detectado'
WHERE folio IS NOT NULL AND folio_origen IS NULL;

UPDATE core.comprobantes_internos
SET numero_documento = to_char(fecha_gasto, 'DDMMYYYY'),
    numero_documento_origen = 'fecha'
WHERE numero_documento IS NULL OR trim(numero_documento) = '';

ALTER TABLE core.comprobantes_internos
    ALTER COLUMN numero_documento SET NOT NULL,
    ALTER COLUMN numero_documento_origen SET NOT NULL,
    ALTER COLUMN numero_documento_origen SET DEFAULT 'fecha';

CREATE INDEX IF NOT EXISTS interpretaciones_folio_idx
    ON ai.interpretaciones (lower(folio)) WHERE folio IS NOT NULL;
CREATE INDEX IF NOT EXISTS facturas_finales_folio_idx
    ON core.facturas_finales (lower(folio)) WHERE folio IS NOT NULL;
CREATE INDEX IF NOT EXISTS comprobantes_internos_numero_idx
    ON core.comprobantes_internos (lower(numero_documento));

CREATE OR REPLACE VIEW analytics.movimientos_gasto AS
SELECT
    ff.id AS movimiento_id,
    'factura_fiscal'::text AS tipo_documento,
    ff.factura_id AS documento_origen_id,
    COALESCE(NULLIF(ff.folio, ''), to_char(ff.fecha_emision, 'DDMMYYYY')) AS folio,
    ff.fecha_emision AS fecha,
    EXTRACT(ISOYEAR FROM ff.fecha_emision)::integer AS anio_iso,
    EXTRACT(WEEK FROM ff.fecha_emision)::integer AS semana_iso,
    s.restaurante,
    s.clave AS sucursal_clave,
    s.nombre AS sucursal,
    p.nombre_normalizado AS proveedor,
    p.rfc AS proveedor_rfc,
    c.nombre AS categoria,
    sc.nombre AS subcategoria,
    cc.nombre AS centro_costo,
    ff.moneda,
    ff.subtotal,
    ff.descuento,
    ff.iva,
    ff.otros_impuestos,
    ff.total,
    'con_cfdi'::text AS estado_fiscal,
    ff.aprobada_en
FROM core.facturas_finales ff
JOIN catalog.sucursales s ON s.id = ff.sucursal_id
JOIN catalog.proveedores p ON p.id = ff.proveedor_id
JOIN catalog.categorias c ON c.id = ff.categoria_id
LEFT JOIN catalog.subcategorias sc ON sc.id = ff.subcategoria_id
LEFT JOIN catalog.centros_costo cc ON cc.id = ff.centro_costo_id
WHERE ff.vigente

UNION ALL

SELECT
    ci.id AS movimiento_id,
    'comprobante_interno'::text AS tipo_documento,
    ci.id AS documento_origen_id,
    ci.numero_documento AS folio,
    ci.fecha_gasto AS fecha,
    EXTRACT(ISOYEAR FROM ci.fecha_gasto)::integer AS anio_iso,
    EXTRACT(WEEK FROM ci.fecha_gasto)::integer AS semana_iso,
    s.restaurante,
    s.clave AS sucursal_clave,
    s.nombre AS sucursal,
    p.nombre_normalizado AS proveedor,
    p.rfc AS proveedor_rfc,
    c.nombre AS categoria,
    sc.nombre AS subcategoria,
    cc.nombre AS centro_costo,
    ci.moneda,
    d.monto AS subtotal,
    0::numeric(14,2) AS descuento,
    0::numeric(14,2) AS iva,
    0::numeric(14,2) AS otros_impuestos,
    d.monto AS total,
    ci.estado_fiscal,
    COALESCE(ci.segunda_aprobacion_en, ci.primera_aprobacion_en) AS aprobada_en
FROM core.comprobantes_internos ci
JOIN core.comprobante_distribuciones d ON d.comprobante_id = ci.id
JOIN catalog.sucursales s ON s.id = d.sucursal_id
JOIN catalog.proveedores p ON p.id = ci.proveedor_id
JOIN catalog.categorias c ON c.id = ci.categoria_id
LEFT JOIN catalog.subcategorias sc ON sc.id = ci.subcategoria_id
LEFT JOIN catalog.centros_costo cc ON cc.id = ci.centro_costo_id
WHERE ci.estado = 'aprobado' AND ci.factura_final_reemplazo_id IS NULL;
