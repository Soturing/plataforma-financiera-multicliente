BEGIN;

CREATE SCHEMA IF NOT EXISTS finance;

INSERT INTO catalog.centros_costo (clave, nombre, activo)
VALUES
    ('COCINA', 'Restaurante / Cocina', true),
    ('BARRA', 'Barra', true),
    ('ADMINISTRACION', 'Administración', true),
    ('GENERAL', 'General', true)
ON CONFLICT (clave) DO UPDATE
SET nombre = EXCLUDED.nombre, activo = true;

UPDATE ai.interpretaciones i
SET subcategoria_id = NULL
FROM catalog.categorias c
WHERE i.categoria_id = c.id AND c.clave NOT IN ('FIJOS', 'VARIABLES');

UPDATE core.facturas_finales ff
SET subcategoria_id = NULL
FROM catalog.categorias c
WHERE ff.categoria_id = c.id AND c.clave NOT IN ('FIJOS', 'VARIABLES');

UPDATE core.comprobantes_internos ci
SET subcategoria_id = NULL
FROM catalog.categorias c
WHERE ci.categoria_id = c.id AND c.clave NOT IN ('FIJOS', 'VARIABLES');

UPDATE catalog.reglas_clasificacion r
SET subcategoria_id = NULL
FROM catalog.categorias c
WHERE r.categoria_id = c.id AND c.clave NOT IN ('FIJOS', 'VARIABLES');

UPDATE ai.interpretaciones i
SET categoria_id = v.id,
    centro_costo_id = CASE
        WHEN antigua.clave = 'BARRA' THEN barra.id
        ELSE COALESCE(i.centro_costo_id, cocina.id)
    END
FROM catalog.categorias antigua
CROSS JOIN catalog.categorias v
CROSS JOIN catalog.centros_costo barra
CROSS JOIN catalog.centros_costo cocina
WHERE i.categoria_id = antigua.id
  AND antigua.clave NOT IN ('FIJOS', 'VARIABLES')
  AND v.clave = 'VARIABLES'
  AND barra.clave = 'BARRA'
  AND cocina.clave = 'COCINA';

UPDATE core.facturas_finales ff
SET categoria_id = v.id,
    centro_costo_id = CASE
        WHEN antigua.clave = 'BARRA' THEN barra.id
        ELSE COALESCE(ff.centro_costo_id, cocina.id)
    END
FROM catalog.categorias antigua
CROSS JOIN catalog.categorias v
CROSS JOIN catalog.centros_costo barra
CROSS JOIN catalog.centros_costo cocina
WHERE ff.categoria_id = antigua.id
  AND antigua.clave NOT IN ('FIJOS', 'VARIABLES')
  AND v.clave = 'VARIABLES'
  AND barra.clave = 'BARRA'
  AND cocina.clave = 'COCINA';

UPDATE core.comprobantes_internos ci
SET categoria_id = v.id,
    centro_costo_id = CASE
        WHEN antigua.clave = 'BARRA' THEN barra.id
        ELSE COALESCE(ci.centro_costo_id, cocina.id)
    END
FROM catalog.categorias antigua
CROSS JOIN catalog.categorias v
CROSS JOIN catalog.centros_costo barra
CROSS JOIN catalog.centros_costo cocina
WHERE ci.categoria_id = antigua.id
  AND antigua.clave NOT IN ('FIJOS', 'VARIABLES')
  AND v.clave = 'VARIABLES'
  AND barra.clave = 'BARRA'
  AND cocina.clave = 'COCINA';

UPDATE catalog.reglas_clasificacion r
SET categoria_id = v.id,
    centro_costo_id = CASE
        WHEN antigua.clave = 'BARRA' THEN barra.id
        ELSE COALESCE(r.centro_costo_id, cocina.id)
    END
FROM catalog.categorias antigua
CROSS JOIN catalog.categorias v
CROSS JOIN catalog.centros_costo barra
CROSS JOIN catalog.centros_costo cocina
WHERE r.categoria_id = antigua.id
  AND antigua.clave NOT IN ('FIJOS', 'VARIABLES')
  AND v.clave = 'VARIABLES'
  AND barra.clave = 'BARRA'
  AND cocina.clave = 'COCINA';

UPDATE catalog.categorias
SET activa = (clave IN ('FIJOS', 'VARIABLES')),
    orden = CASE clave WHEN 'FIJOS' THEN 10 WHEN 'VARIABLES' THEN 20 ELSE orden END
WHERE clave IN ('FIJOS', 'VARIABLES', 'BARRA', 'RESTAURANTE');

WITH nuevas(categoria, clave, nombre) AS (
    VALUES
        ('FIJOS', 'RENTA', 'Renta'),
        ('FIJOS', 'NOMINA_FIJA', 'Nómina fija'),
        ('FIJOS', 'SERVICIOS_FIJOS', 'Servicios fijos'),
        ('FIJOS', 'LICENCIAS', 'Licencias y suscripciones'),
        ('VARIABLES', 'INSUMOS', 'Insumos'),
        ('VARIABLES', 'BEBIDAS', 'Bebidas'),
        ('VARIABLES', 'MANTENIMIENTO', 'Mantenimiento'),
        ('VARIABLES', 'COMISIONES', 'Comisiones'),
        ('VARIABLES', 'SERVICIOS_VARIABLES', 'Servicios variables'),
        ('VARIABLES', 'OTROS_VARIABLES', 'Otros variables')
)
INSERT INTO catalog.subcategorias (categoria_id, clave, nombre, activa)
SELECT c.id, n.clave, n.nombre, true
FROM nuevas n JOIN catalog.categorias c ON c.clave = n.categoria
ON CONFLICT (categoria_id, clave) DO UPDATE
SET nombre = EXCLUDED.nombre, activa = true;

CREATE TABLE IF NOT EXISTS audit.cambios_catalogo (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entidad text NOT NULL CHECK (entidad IN ('subcategoria', 'centro_costo')),
    entidad_id uuid NOT NULL,
    accion text NOT NULL CHECK (accion IN ('crear', 'actualizar', 'activar', 'desactivar')),
    antes jsonb,
    despues jsonb NOT NULL,
    realizado_por text NOT NULL,
    realizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS finance.ventas (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sucursal_id uuid NOT NULL REFERENCES catalog.sucursales(id),
    fecha date NOT NULL,
    monto_neto numeric(14,2) NOT NULL CHECK (monto_neto >= 0),
    fuente text NOT NULL DEFAULT 'manual' CHECK (fuente IN ('manual', 'wansoft', 'demo')),
    referencia text NOT NULL,
    es_demo boolean NOT NULL DEFAULT false,
    registrada_por text NOT NULL,
    registrada_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE (sucursal_id, fecha, fuente, referencia)
);

CREATE INDEX IF NOT EXISTS ventas_periodo_idx
    ON finance.ventas (fecha, sucursal_id);

CREATE TABLE IF NOT EXISTS finance.parametros_equilibrio (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sucursal_id uuid NOT NULL REFERENCES catalog.sucursales(id),
    vigente_desde date NOT NULL,
    gasto_fijo_semanal numeric(14,2) NOT NULL CHECK (gasto_fijo_semanal >= 0),
    es_demo boolean NOT NULL DEFAULT false,
    registrado_por text NOT NULL,
    registrado_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE (sucursal_id, vigente_desde)
);

WITH datos(clave, fecha, monto) AS (
    VALUES
        ('DEMO-01', DATE '2026-08-03', 15000.00), ('DEMO-01', DATE '2026-08-04', 16000.00),
        ('DEMO-01', DATE '2026-08-05', 17000.00), ('DEMO-01', DATE '2026-08-06', 18000.00),
        ('DEMO-01', DATE '2026-08-07', 22000.00), ('DEMO-01', DATE '2026-08-08', 20000.00),
        ('DEMO-01', DATE '2026-08-09', 12000.00),
        ('DEMO-A', DATE '2026-08-03', 23000.00), ('DEMO-A', DATE '2026-08-04', 24000.00),
        ('DEMO-A', DATE '2026-08-05', 25000.00), ('DEMO-A', DATE '2026-08-06', 27000.00),
        ('DEMO-A', DATE '2026-08-07', 32000.00), ('DEMO-A', DATE '2026-08-08', 29000.00),
        ('DEMO-A', DATE '2026-08-09', 20000.00),
        ('DEMO-01', DATE '2026-08-10', 18000.00), ('DEMO-01', DATE '2026-08-11', 19000.00),
        ('DEMO-01', DATE '2026-08-12', 20000.00), ('DEMO-01', DATE '2026-08-13', 21000.00),
        ('DEMO-01', DATE '2026-08-14', 25000.00), ('DEMO-01', DATE '2026-08-15', 23000.00),
        ('DEMO-01', DATE '2026-08-16', 14000.00),
        ('DEMO-A', DATE '2026-08-10', 27000.00), ('DEMO-A', DATE '2026-08-11', 29000.00),
        ('DEMO-A', DATE '2026-08-12', 30000.00), ('DEMO-A', DATE '2026-08-13', 31000.00),
        ('DEMO-A', DATE '2026-08-14', 36000.00), ('DEMO-A', DATE '2026-08-15', 34000.00),
        ('DEMO-A', DATE '2026-08-16', 23000.00)
)
INSERT INTO finance.ventas (
    sucursal_id, fecha, monto_neto, fuente, referencia, es_demo, registrada_por
)
SELECT s.id, d.fecha, d.monto, 'demo', 'SEMANA-DEMO', true, 'migracion-010'
FROM datos d JOIN catalog.sucursales s ON s.clave = d.clave
ON CONFLICT (sucursal_id, fecha, fuente, referencia) DO NOTHING;

INSERT INTO finance.parametros_equilibrio (
    sucursal_id, vigente_desde, gasto_fijo_semanal, es_demo, registrado_por
)
SELECT s.id, DATE '2026-01-01',
       CASE s.clave WHEN 'DEMO-A' THEN 45000.00 ELSE 35000.00 END,
       true, 'migracion-010'
FROM catalog.sucursales s
WHERE s.clave IN ('DEMO-A', 'DEMO-01')
ON CONFLICT (sucursal_id, vigente_desde) DO UPDATE
SET gasto_fijo_semanal = EXCLUDED.gasto_fijo_semanal,
    es_demo = true,
    registrado_por = EXCLUDED.registrado_por;

CREATE OR REPLACE VIEW finance.estado_resultados_semanal AS
WITH ventas AS (
    SELECT
        v.sucursal_id,
        EXTRACT(ISOYEAR FROM v.fecha)::integer AS anio_iso,
        EXTRACT(WEEK FROM v.fecha)::integer AS semana_iso,
        sum(v.monto_neto)::numeric(14,2) AS ventas,
        bool_and(v.es_demo) AS ventas_demo
    FROM finance.ventas v
    GROUP BY v.sucursal_id, EXTRACT(ISOYEAR FROM v.fecha), EXTRACT(WEEK FROM v.fecha)
), gastos AS (
    SELECT
        s.id AS sucursal_id,
        m.anio_iso,
        m.semana_iso,
        sum(m.total) FILTER (WHERE upper(m.categoria) = 'FIJOS')::numeric(14,2) AS gastos_fijos,
        sum(m.total) FILTER (WHERE upper(m.categoria) = 'VARIABLES')::numeric(14,2) AS costos_variables
    FROM analytics.movimientos_gasto m
    JOIN catalog.sucursales s ON s.clave = m.sucursal_clave
    GROUP BY s.id, m.anio_iso, m.semana_iso
), periodos AS (
    SELECT sucursal_id, anio_iso, semana_iso FROM ventas
    UNION
    SELECT sucursal_id, anio_iso, semana_iso FROM gastos
)
SELECT
    p.sucursal_id,
    s.clave AS sucursal_clave,
    s.nombre AS sucursal,
    s.restaurante,
    p.anio_iso,
    p.semana_iso,
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
