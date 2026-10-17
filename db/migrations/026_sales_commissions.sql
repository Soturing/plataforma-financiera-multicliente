-- D-017: comisiones por sucursal con proyección (porcentaje ajustable) y cierre real mensual.
BEGIN;

CREATE TABLE IF NOT EXISTS finance.comision_parametros (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sucursal_id uuid NOT NULL REFERENCES catalog.sucursales(id),
    concepto text NOT NULL CHECK (concepto IN ('VISA', 'AMEX', 'BANCO', 'APPS', 'SERVICIOS')),
    canal text CHECK (canal IN ('UBER', 'RAPPI')),
    base text NOT NULL CHECK (base IN ('visa', 'amex', 'credito', 'uber', 'rappi', 'ventas_netas', 'monto_mensual')),
    porcentaje numeric(8,6) CHECK (porcentaje >= 0 AND porcentaje <= 1),
    monto_mensual numeric(14,2) CHECK (monto_mensual >= 0),
    actualizada_por text NOT NULL,
    actualizada_en timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (base = 'monto_mensual' AND monto_mensual IS NOT NULL)
        OR (base <> 'monto_mensual' AND porcentaje IS NOT NULL)
    ),
    UNIQUE NULLS NOT DISTINCT (sucursal_id, concepto, canal)
);

CREATE TABLE IF NOT EXISTS finance.comision_cierres (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sucursal_id uuid NOT NULL REFERENCES catalog.sucursales(id),
    concepto text NOT NULL CHECK (concepto IN ('VISA', 'AMEX', 'BANCO', 'APPS', 'SERVICIOS')),
    anio smallint NOT NULL CHECK (anio BETWEEN 2000 AND 2100),
    mes smallint NOT NULL CHECK (mes BETWEEN 1 AND 12),
    importe_real numeric(14,2) NOT NULL CHECK (importe_real >= 0),
    actualizado_por text NOT NULL,
    actualizado_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE (sucursal_id, concepto, anio, mes)
);

-- Parámetros iniciales de la demo (equivalen a las tasas que antes estaban fijas en código).
WITH base(sucursal, concepto, canal, base, porcentaje) AS (
    VALUES
        ('DEMO-A', 'VISA', NULL, 'visa', 0.026), ('DEMO-A', 'AMEX', NULL, 'amex', 0.038),
        ('DEMO-A', 'BANCO', NULL, 'credito', 0.022),
        ('DEMO-A', 'APPS', 'UBER', 'uber', 0.31), ('DEMO-A', 'APPS', 'RAPPI', 'rappi', 0.36),
        ('DEMO-B', 'VISA', NULL, 'visa', 0.026), ('DEMO-B', 'AMEX', NULL, 'amex', 0.038),
        ('DEMO-B', 'BANCO', NULL, 'credito', 0.022),
        ('DEMO-B', 'APPS', 'UBER', 'uber', 0.31), ('DEMO-B', 'APPS', 'RAPPI', 'rappi', 0.36),
        ('DEMO-C', 'VISA', NULL, 'visa', 0.026), ('DEMO-C', 'AMEX', NULL, 'amex', 0.038),
        ('DEMO-C', 'BANCO', NULL, 'credito', 0.022)
)
INSERT INTO finance.comision_parametros (sucursal_id, concepto, canal, base, porcentaje, actualizada_por)
SELECT s.id, b.concepto, b.canal, b.base, b.porcentaje, 'migracion-026'
FROM base b JOIN catalog.sucursales s ON s.clave = b.sucursal
ON CONFLICT (sucursal_id, concepto, canal) DO NOTHING;

COMMIT;
