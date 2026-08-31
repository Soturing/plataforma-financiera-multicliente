BEGIN;

CREATE TABLE IF NOT EXISTS finance.provisiones_fijas (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sucursal_id uuid NOT NULL REFERENCES catalog.sucursales(id),
    clave text NOT NULL,
    concepto text NOT NULL,
    periodicidad text NOT NULL CHECK (periodicidad IN ('semanal', 'mensual', 'bimestral', 'anual')),
    importe_periodo numeric(14,2) NOT NULL CHECK (importe_periodo >= 0),
    es_nomina boolean NOT NULL DEFAULT false,
    vigente_desde date NOT NULL DEFAULT DATE '2026-01-01',
    activa boolean NOT NULL DEFAULT true,
    actualizada_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE (sucursal_id, clave, vigente_desde)
);

CREATE TABLE IF NOT EXISTS finance.cierres_provision_fija (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provision_id uuid NOT NULL REFERENCES finance.provisiones_fijas(id) ON DELETE CASCADE,
    periodo_desde date NOT NULL,
    periodo_hasta date NOT NULL,
    importe_real numeric(14,2) NOT NULL CHECK (importe_real >= 0),
    actualizado_por text NOT NULL,
    actualizado_en timestamptz NOT NULL DEFAULT now(),
    CHECK (periodo_desde <= periodo_hasta),
    UNIQUE (provision_id, periodo_desde, periodo_hasta)
);

WITH datos(sucursal, clave, concepto, periodicidad, importe, es_nomina) AS (
    VALUES
        ('DEMO-B', 'RENTA', 'Renta', 'mensual', 120000.00, false),
        ('DEMO-B', 'AGUA_DRENAJE', 'Agua y drenaje', 'anual', 72000.00, false),
        ('DEMO-B', 'CFE', 'C.F.E.', 'bimestral', 90000.00, false),
        ('DEMO-B', 'FUMIGACION', 'Fumigacion', 'semanal', 1500.00, false),
        ('DEMO-B', 'SISTEMA_POS', 'Sistema de punto de venta', 'mensual', 2500.00, false),
        ('DEMO-B', 'SERVICIO_OPERATIVO', 'Servicio operativo', 'semanal', 3000.00, false),
        ('DEMO-B', 'SEGURO', 'Seguro', 'anual', 36000.00, false),
        ('DEMO-B', 'NOMINA', 'Nomina', 'semanal', 35000.00, true),
        ('DEMO-A', 'RENTA', 'Renta', 'mensual', 100000.00, false),
        ('DEMO-A', 'AGUA_DRENAJE', 'Agua y drenaje', 'anual', 60000.00, false),
        ('DEMO-A', 'CFE', 'C.F.E.', 'bimestral', 80000.00, false),
        ('DEMO-A', 'FUMIGACION', 'Fumigacion', 'semanal', 1200.00, false),
        ('DEMO-A', 'SISTEMA_POS', 'Sistema de punto de venta', 'mensual', 2500.00, false),
        ('DEMO-A', 'SERVICIO_OPERATIVO', 'Servicio operativo', 'semanal', 3000.00, false),
        ('DEMO-A', 'NOMINA', 'Nomina', 'semanal', 30000.00, true),
        ('DEMO-C', 'RENTA', 'Renta', 'mensual', 90000.00, false),
        ('DEMO-C', 'AGUA_DRENAJE', 'Agua y drenaje', 'anual', 48000.00, false),
        ('DEMO-C', 'CFE', 'C.F.E.', 'bimestral', 70000.00, false),
        ('DEMO-C', 'SERVICIO_EXTERNO_A', 'Servicio externo A', 'mensual', 6000.00, false),
        ('DEMO-C', 'SERVICIO_EXTERNO_B', 'Servicio externo B', 'mensual', 8000.00, false),
        ('DEMO-C', 'NOMINA', 'Nomina', 'semanal', 28000.00, true),
        ('DEMO-C', 'SERVICIO_OPERATIVO', 'Servicio operativo', 'semanal', 2500.00, false),
        ('DEMO-C', 'NOMINA_ADMIN', 'Nomina administrativa', 'semanal', 5000.00, true)
)
INSERT INTO finance.provisiones_fijas (
    sucursal_id, clave, concepto, periodicidad, importe_periodo, es_nomina,
    vigente_desde, activa
)
SELECT s.id, d.clave, d.concepto, d.periodicidad, d.importe, d.es_nomina,
       DATE '2026-01-01', true
FROM datos d
JOIN catalog.sucursales s ON s.clave = d.sucursal
ON CONFLICT (sucursal_id, clave, vigente_desde) DO UPDATE
SET concepto = EXCLUDED.concepto,
    periodicidad = EXCLUDED.periodicidad,
    importe_periodo = EXCLUDED.importe_periodo,
    es_nomina = EXCLUDED.es_nomina,
    activa = true,
    actualizada_en = now();

-- Base semanal estimada de gastos fijos. Los importes mensuales, bimestrales
-- y anuales se convierten a costo anual y se distribuyen entre 52 semanas
-- fiscales; los conceptos semanales conservan su importe.
WITH bases(clave, gasto_fijo_semanal) AS (
    VALUES
        ('DEMO-B', 60000.00::numeric(14,2)),
        ('DEMO-A', 52000.00::numeric(14,2)),
        ('DEMO-C', 50000.00::numeric(14,2))
)
INSERT INTO finance.parametros_equilibrio (
    sucursal_id, vigente_desde, gasto_fijo_semanal, es_demo, registrado_por
)
SELECT s.id, DATE '2026-01-01', b.gasto_fijo_semanal, true,
       'migracion-023-fijos-estimados'
FROM bases b
JOIN catalog.sucursales s ON s.clave = b.clave
ON CONFLICT (sucursal_id, vigente_desde) DO UPDATE
SET gasto_fijo_semanal = EXCLUDED.gasto_fijo_semanal,
    es_demo = true,
    registrado_por = EXCLUDED.registrado_por;

COMMIT;
