-- D-017: nueve categorías de gasto con subcategorías editables y sin centros de costo.
-- Los datos de la demo se reasignan; los centros de costo se eliminan por completo.
BEGIN;

ALTER TABLE catalog.categorias
    ADD COLUMN IF NOT EXISTS tipo_costo text NOT NULL DEFAULT 'variable'
        CHECK (tipo_costo IN ('fijo', 'variable')),
    ADD COLUMN IF NOT EXISTS admite_facturas boolean NOT NULL DEFAULT true;

INSERT INTO catalog.categorias (clave, nombre, activa, orden, tipo_costo, admite_facturas)
VALUES
    ('FIJOS', 'Gastos fijos', true, 10, 'fijo', true),
    ('NOMINA', 'Nómina', true, 20, 'fijo', false),
    ('COMISIONES', 'Comisiones', true, 30, 'variable', false),
    ('VARIABLES_OPERATIVOS', 'Variables operativos', true, 40, 'variable', true),
    ('IMPREVISTOS', 'Gastos imprevistos', true, 50, 'variable', true),
    ('MANTENIMIENTO', 'Mantenimiento', true, 60, 'variable', true),
    ('GASOLINA', 'Gasolina', true, 70, 'variable', true),
    ('GASTOS_BARRA', 'Gastos Barra', true, 80, 'variable', true),
    ('GASTOS_RESTAURANTE', 'Gastos Restaurantes', true, 90, 'variable', true)
ON CONFLICT (clave) DO UPDATE
SET nombre = EXCLUDED.nombre, activa = true, orden = EXCLUDED.orden,
    tipo_costo = EXCLUDED.tipo_costo, admite_facturas = EXCLUDED.admite_facturas;

INSERT INTO catalog.subcategorias (categoria_id, clave, nombre, activa)
SELECT c.id, v.clave, v.nombre, true
FROM (VALUES
    ('GASTOS_BARRA', 'BEBIDAS', 'Bebidas'),
    ('GASTOS_RESTAURANTE', 'INSUMOS', 'Insumos')
) v(categoria, clave, nombre)
JOIN catalog.categorias c ON c.clave = v.categoria
ON CONFLICT (categoria_id, clave) DO UPDATE SET nombre = EXCLUDED.nombre, activa = true;

-- Reasignación de documentos y reglas existentes a las categorías nuevas.
CREATE TEMP TABLE _mapa_categorias ON COMMIT DROP AS
WITH origen AS (
    SELECT c.id AS cat_id, c.clave AS cat, sc.id AS sub_id, sc.clave AS sub
    FROM catalog.categorias c
    LEFT JOIN catalog.subcategorias sc ON sc.categoria_id = c.id
    WHERE c.clave IN ('FIJOS', 'VARIABLES', 'BARRA', 'RESTAURANTE')
    UNION
    SELECT c.id, c.clave, NULL::uuid, NULL::text
    FROM catalog.categorias c
    WHERE c.clave IN ('FIJOS', 'VARIABLES', 'BARRA', 'RESTAURANTE')
), destino AS (
    SELECT cat_id, sub_id,
           CASE
               WHEN cat = 'FIJOS' AND sub = 'NOMINA_FIJA' THEN 'NOMINA'
               WHEN cat = 'FIJOS' THEN 'FIJOS'
               WHEN cat = 'BARRA' THEN 'GASTOS_BARRA'
               WHEN cat = 'RESTAURANTE' THEN 'GASTOS_RESTAURANTE'
               WHEN sub = 'INSUMOS' THEN 'GASTOS_RESTAURANTE'
               WHEN sub = 'BEBIDAS' THEN 'GASTOS_BARRA'
               WHEN sub = 'MANTENIMIENTO' THEN 'MANTENIMIENTO'
               WHEN sub = 'IMPREVISTOS' THEN 'IMPREVISTOS'
               ELSE 'VARIABLES_OPERATIVOS'
           END AS nueva_cat,
           CASE
               WHEN cat = 'FIJOS' AND sub IS DISTINCT FROM 'NOMINA_FIJA' THEN sub
               WHEN sub IN ('INSUMOS', 'BEBIDAS') THEN sub
           END AS nueva_sub
    FROM origen
)
SELECT d.cat_id AS cat_anterior, d.sub_id AS sub_anterior,
       nc.id AS cat_nueva, ns.id AS sub_nueva
FROM destino d
JOIN catalog.categorias nc ON nc.clave = d.nueva_cat
LEFT JOIN catalog.subcategorias ns ON ns.categoria_id = nc.id AND ns.clave = d.nueva_sub;

DO $$
DECLARE
    tabla text;
BEGIN
    FOREACH tabla IN ARRAY ARRAY[
        'ai.interpretaciones', 'core.facturas_finales',
        'core.comprobantes_internos', 'catalog.reglas_clasificacion'
    ] LOOP
        EXECUTE format(
            'UPDATE %s t SET categoria_id = m.cat_nueva, subcategoria_id = m.sub_nueva
             FROM _mapa_categorias m
             WHERE t.categoria_id = m.cat_anterior
               AND t.subcategoria_id IS NOT DISTINCT FROM m.sub_anterior
               AND (m.cat_anterior, m.sub_anterior) IS DISTINCT FROM (m.cat_nueva, m.sub_nueva)',
            tabla
        );
    END LOOP;
END $$;

UPDATE catalog.categorias SET activa = false
WHERE clave IN ('VARIABLES', 'BARRA', 'RESTAURANTE');

UPDATE catalog.subcategorias sc SET activa = false
FROM catalog.categorias c
WHERE sc.categoria_id = c.id
  AND (c.clave IN ('VARIABLES', 'BARRA', 'RESTAURANTE')
       OR (c.clave = 'FIJOS' AND sc.clave = 'NOMINA_FIJA'));

-- Centros de costo: se retiran de documentos, reglas y vistas.
DROP VIEW IF EXISTS analytics.estado_resultados_semanal;
DROP VIEW IF EXISTS finance.estado_resultados_semanal;
DROP VIEW IF EXISTS analytics.movimientos_gasto;
DROP VIEW IF EXISTS analytics.facturas_consumo;

ALTER TABLE ai.interpretaciones DROP COLUMN centro_costo_id;
ALTER TABLE core.facturas_finales DROP COLUMN centro_costo_id;
ALTER TABLE core.comprobantes_internos DROP COLUMN centro_costo_id;
ALTER TABLE catalog.reglas_clasificacion DROP COLUMN centro_costo_id;
DROP TABLE catalog.centros_costo;

CREATE VIEW analytics.facturas_consumo AS
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
WHERE ff.vigente AND ff.genera_gasto;

CREATE VIEW analytics.movimientos_gasto AS
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
    ff.moneda,
    ff.subtotal,
    ff.descuento,
    ff.iva,
    ff.otros_impuestos,
    ff.total,
    ff.estado_fiscal,
    ff.aprobada_en,
    c.clave AS categoria_clave,
    c.tipo_costo
FROM core.facturas_finales ff
JOIN catalog.sucursales s ON s.id = ff.sucursal_id
JOIN catalog.proveedores p ON p.id = ff.proveedor_id
JOIN catalog.categorias c ON c.id = ff.categoria_id
LEFT JOIN catalog.subcategorias sc ON sc.id = ff.subcategoria_id
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
    ci.moneda,
    d.monto AS subtotal,
    0::numeric(14,2) AS descuento,
    0::numeric(14,2) AS iva,
    0::numeric(14,2) AS otros_impuestos,
    d.monto AS total,
    ci.estado_fiscal,
    ci.primera_aprobacion_en AS aprobada_en,
    c.clave AS categoria_clave,
    c.tipo_costo
FROM core.comprobantes_internos ci
JOIN core.comprobante_distribuciones d ON d.comprobante_id = ci.id
JOIN catalog.sucursales s ON s.id = d.sucursal_id
JOIN catalog.proveedores p ON p.id = ci.proveedor_id
JOIN catalog.categorias c ON c.id = ci.categoria_id
LEFT JOIN catalog.subcategorias sc ON sc.id = ci.subcategoria_id
WHERE ci.estado = 'aprobado' AND ci.factura_final_reemplazo_id IS NULL;

CREATE VIEW analytics.estado_resultados_semanal AS
SELECT
    anio_iso,
    semana_iso,
    restaurante,
    sucursal_clave,
    sucursal,
    categoria,
    subcategoria,
    moneda,
    COUNT(DISTINCT movimiento_id) AS facturas,
    SUM(subtotal) AS subtotal,
    SUM(descuento) AS descuento,
    SUM(iva) AS iva,
    SUM(otros_impuestos) AS otros_impuestos,
    SUM(total) AS total
FROM analytics.movimientos_gasto
GROUP BY anio_iso, semana_iso, restaurante, sucursal_clave, sucursal,
         categoria, subcategoria, moneda;

CREATE VIEW finance.estado_resultados_semanal AS
WITH ventas AS (
    SELECT v.sucursal_id,
           EXTRACT(ISOYEAR FROM v.fecha)::integer AS anio_iso,
           EXTRACT(WEEK FROM v.fecha)::integer AS semana_iso,
           sum(v.monto_neto)::numeric(14,2) AS ventas,
           bool_and(v.es_demo) AS ventas_demo
    FROM finance.ventas v
    GROUP BY v.sucursal_id, EXTRACT(ISOYEAR FROM v.fecha), EXTRACT(WEEK FROM v.fecha)
), movimientos_semanales AS (
    SELECT m.*,
           COALESCE(ps.anio_iso, m.anio_iso) AS anio_aplicacion,
           COALESCE(ps.semana_iso, m.semana_iso) AS semana_aplicacion,
           COALESCE(ps.monto, m.total) AS total_aplicado
    FROM analytics.movimientos_gasto m
    LEFT JOIN finance.periodificaciones_gasto pg ON
        (m.tipo_documento = 'comprobante_interno' AND pg.comprobante_id = m.documento_origen_id)
        OR (m.tipo_documento <> 'comprobante_interno' AND pg.factura_id = m.documento_origen_id)
    LEFT JOIN finance.periodificacion_semanas ps ON ps.periodificacion_id = pg.id
), gastos AS (
    SELECT s.id AS sucursal_id,
           m.anio_aplicacion AS anio_iso,
           m.semana_aplicacion AS semana_iso,
           sum(m.total_aplicado) FILTER (WHERE m.tipo_costo = 'fijo')::numeric(14,2) AS gastos_fijos,
           sum(m.total_aplicado) FILTER (WHERE m.tipo_costo = 'variable')::numeric(14,2) AS costos_variables
    FROM movimientos_semanales m
    JOIN catalog.sucursales s ON s.clave = m.sucursal_clave
    GROUP BY s.id, m.anio_aplicacion, m.semana_aplicacion
), periodos AS (
    SELECT sucursal_id, anio_iso, semana_iso FROM ventas
    UNION
    SELECT sucursal_id, anio_iso, semana_iso FROM gastos
)
SELECT p.sucursal_id, s.clave AS sucursal_clave, s.nombre AS sucursal,
       s.restaurante, p.anio_iso, p.semana_iso,
       COALESCE(v.ventas, 0)::numeric(14,2) AS ventas,
       COALESCE(g.costos_variables, 0)::numeric(14,2) AS costos_variables,
       COALESCE(g.gastos_fijos, 0)::numeric(14,2) AS gastos_fijos,
       (COALESCE(v.ventas, 0) - COALESCE(g.costos_variables, 0))::numeric(14,2) AS margen_contribucion,
       (COALESCE(v.ventas, 0) - COALESCE(g.costos_variables, 0) - COALESCE(g.gastos_fijos, 0))::numeric(14,2) AS utilidad_operativa,
       COALESCE(v.ventas_demo, false) AS ventas_demo
FROM periodos p
JOIN catalog.sucursales s ON s.id = p.sucursal_id
LEFT JOIN ventas v USING (sucursal_id, anio_iso, semana_iso)
LEFT JOIN gastos g USING (sucursal_id, anio_iso, semana_iso);

COMMIT;
