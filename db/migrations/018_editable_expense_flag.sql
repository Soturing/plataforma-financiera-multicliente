BEGIN;

ALTER TABLE core.facturas_finales
    ADD COLUMN IF NOT EXISTS genera_gasto boolean NOT NULL DEFAULT true;

CREATE OR REPLACE VIEW analytics.facturas_consumo AS
SELECT
    ff.id AS factura_final_id,
    ff.factura_id,
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
    ff.aprobada_en
FROM core.facturas_finales ff
JOIN catalog.sucursales s ON s.id = ff.sucursal_id
JOIN catalog.proveedores p ON p.id = ff.proveedor_id
JOIN catalog.categorias c ON c.id = ff.categoria_id
LEFT JOIN catalog.subcategorias sc ON sc.id = ff.subcategoria_id
LEFT JOIN catalog.centros_costo cc ON cc.id = ff.centro_costo_id
WHERE ff.vigente AND ff.genera_gasto;

CREATE OR REPLACE VIEW analytics.movimientos_gasto AS
SELECT
    ff.id AS movimiento_id,
    ff.tipo_documento::text AS tipo_documento,
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
    ff.estado_fiscal,
    ff.aprobada_en
FROM core.facturas_finales ff
JOIN catalog.sucursales s ON s.id = ff.sucursal_id
JOIN catalog.proveedores p ON p.id = ff.proveedor_id
JOIN catalog.categorias c ON c.id = ff.categoria_id
LEFT JOIN catalog.subcategorias sc ON sc.id = ff.subcategoria_id
LEFT JOIN catalog.centros_costo cc ON cc.id = ff.centro_costo_id
WHERE ff.vigente AND ff.genera_gasto

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
    ci.primera_aprobacion_en AS aprobada_en
FROM core.comprobantes_internos ci
JOIN core.comprobante_distribuciones d ON d.comprobante_id = ci.id
JOIN catalog.sucursales s ON s.id = d.sucursal_id
JOIN catalog.proveedores p ON p.id = ci.proveedor_id
JOIN catalog.categorias c ON c.id = ci.categoria_id
LEFT JOIN catalog.subcategorias sc ON sc.id = ci.subcategoria_id
LEFT JOIN catalog.centros_costo cc ON cc.id = ci.centro_costo_id
WHERE ci.estado = 'aprobado' AND ci.factura_final_reemplazo_id IS NULL;

COMMIT;
