BEGIN;

CREATE TABLE IF NOT EXISTS finance.periodificaciones_gasto (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    factura_id uuid REFERENCES core.facturas(id) ON DELETE CASCADE,
    comprobante_id uuid REFERENCES core.comprobantes_internos(id) ON DELETE CASCADE,
    tipo text NOT NULL CHECK (tipo IN ('una_semana', 'mensual', 'bimestral', 'personalizado')),
    periodo_desde date NOT NULL,
    periodo_hasta date NOT NULL,
    total_documento numeric(14,2) NOT NULL CHECK (total_documento > 0),
    configurada_por text NOT NULL,
    creada_en timestamptz NOT NULL DEFAULT now(),
    actualizada_en timestamptz NOT NULL DEFAULT now(),
    CHECK ((factura_id IS NULL) <> (comprobante_id IS NULL)),
    CHECK (periodo_desde <= periodo_hasta)
);

CREATE UNIQUE INDEX IF NOT EXISTS periodificaciones_factura_idx
    ON finance.periodificaciones_gasto (factura_id) WHERE factura_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS periodificaciones_comprobante_idx
    ON finance.periodificaciones_gasto (comprobante_id) WHERE comprobante_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS finance.periodificacion_semanas (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    periodificacion_id uuid NOT NULL REFERENCES finance.periodificaciones_gasto(id) ON DELETE CASCADE,
    anio_iso integer NOT NULL,
    semana_iso smallint NOT NULL CHECK (semana_iso BETWEEN 1 AND 53),
    fecha_desde date NOT NULL,
    fecha_hasta date NOT NULL,
    monto numeric(14,2) NOT NULL CHECK (monto > 0),
    UNIQUE (periodificacion_id, anio_iso, semana_iso)
);

CREATE INDEX IF NOT EXISTS periodificacion_semanas_periodo_idx
    ON finance.periodificacion_semanas (anio_iso, semana_iso);

CREATE TABLE IF NOT EXISTS catalog.reglas_periodificacion (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    proveedor_id uuid NOT NULL REFERENCES catalog.proveedores(id) ON DELETE CASCADE,
    subcategoria_id uuid REFERENCES catalog.subcategorias(id) ON DELETE CASCADE,
    tipo text NOT NULL CHECK (tipo IN ('una_semana', 'mensual', 'bimestral', 'personalizado')),
    activa boolean NOT NULL DEFAULT true,
    aprendida_por text NOT NULL,
    creada_en timestamptz NOT NULL DEFAULT now(),
    actualizada_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (proveedor_id, subcategoria_id)
);

CREATE OR REPLACE VIEW finance.estado_resultados_semanal AS
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
           sum(m.total_aplicado) FILTER (WHERE upper(m.categoria) = 'FIJOS')::numeric(14,2) AS gastos_fijos,
           sum(m.total_aplicado) FILTER (WHERE upper(m.categoria) = 'VARIABLES')::numeric(14,2) AS costos_variables
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
