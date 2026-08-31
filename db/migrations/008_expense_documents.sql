ALTER TYPE core.tipo_documento ADD VALUE IF NOT EXISTS 'ticket_compra';
ALTER TYPE core.tipo_documento ADD VALUE IF NOT EXISTS 'nota_venta';
ALTER TYPE core.tipo_documento ADD VALUE IF NOT EXISTS 'remision';

ALTER TABLE core.facturas_finales
    ADD COLUMN IF NOT EXISTS tipo_documento core.tipo_documento NOT NULL DEFAULT 'factura_fiscal',
    ADD COLUMN IF NOT EXISTS estado_fiscal text NOT NULL DEFAULT 'con_cfdi';

UPDATE core.facturas_finales ff
SET tipo_documento = COALESCE((
        SELECT cd.tipo FROM core.clasificaciones_documentales cd
        WHERE cd.factura_id = ff.factura_id ORDER BY cd.version DESC LIMIT 1
    ), 'factura_fiscal'::core.tipo_documento),
    estado_fiscal = CASE WHEN COALESCE((
        SELECT cd.tipo::text FROM core.clasificaciones_documentales cd
        WHERE cd.factura_id = ff.factura_id ORDER BY cd.version DESC LIMIT 1
    ), 'factura_fiscal') = 'factura_fiscal' THEN 'con_cfdi' ELSE 'no_deducible' END;

ALTER TABLE core.facturas_finales
    ADD CONSTRAINT facturas_finales_estado_fiscal_valido
    CHECK (estado_fiscal IN ('no_deducible', 'pendiente_cfdi', 'con_cfdi'));

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
