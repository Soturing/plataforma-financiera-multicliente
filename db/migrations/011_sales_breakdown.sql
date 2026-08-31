BEGIN;

ALTER TABLE finance.ventas
    ADD COLUMN IF NOT EXISTS efectivo numeric(14,2) NOT NULL DEFAULT 0 CHECK (efectivo >= 0),
    ADD COLUMN IF NOT EXISTS dolares numeric(14,2) NOT NULL DEFAULT 0 CHECK (dolares >= 0),
    ADD COLUMN IF NOT EXISTS tipo_cambio numeric(12,4) NOT NULL DEFAULT 0 CHECK (tipo_cambio >= 0),
    ADD COLUMN IF NOT EXISTS rappi numeric(14,2) NOT NULL DEFAULT 0 CHECK (rappi >= 0),
    ADD COLUMN IF NOT EXISTS uber numeric(14,2) NOT NULL DEFAULT 0 CHECK (uber >= 0),
    ADD COLUMN IF NOT EXISTS visa numeric(14,2) NOT NULL DEFAULT 0 CHECK (visa >= 0),
    ADD COLUMN IF NOT EXISTS amex numeric(14,2) NOT NULL DEFAULT 0 CHECK (amex >= 0),
    ADD COLUMN IF NOT EXISTS venta_otro numeric(14,2) NOT NULL DEFAULT 0 CHECK (venta_otro >= 0),
    ADD COLUMN IF NOT EXISTS venta_aplicaciones numeric(14,2) NOT NULL DEFAULT 0 CHECK (venta_aplicaciones >= 0),
    ADD COLUMN IF NOT EXISTS venta_alimentos numeric(14,2) NOT NULL DEFAULT 0 CHECK (venta_alimentos >= 0),
    ADD COLUMN IF NOT EXISTS venta_bebidas numeric(14,2) NOT NULL DEFAULT 0 CHECK (venta_bebidas >= 0),
    ADD COLUMN IF NOT EXISTS visitas integer NOT NULL DEFAULT 0 CHECK (visitas >= 0),
    ADD COLUMN IF NOT EXISTS faltante numeric(14,2) NOT NULL DEFAULT 0 CHECK (faltante >= 0),
    ADD COLUMN IF NOT EXISTS sobrante numeric(14,2) NOT NULL DEFAULT 0 CHECK (sobrante >= 0),
    ADD COLUMN IF NOT EXISTS total_capturado_manual boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS actualizada_en timestamptz NOT NULL DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS ventas_sucursal_fecha_unica
    ON finance.ventas (sucursal_id, fecha);

WITH datos(
    fecha, efectivo, rappi, uber, visa, amex,
    venta_otro, venta_aplicaciones, venta_alimentos, venta_bebidas, visitas
) AS (
    VALUES
        (DATE '2026-07-20', 4500.00,  500.00,    0.00, 12000.00, 1000.00, 2000.00,  500.00, 11500.00, 4000.00, 50),
        (DATE '2026-07-21', 5000.00,  500.00,  500.00, 13000.00, 1000.00, 2000.00, 1000.00, 13000.00, 4000.00, 55),
        (DATE '2026-07-22', 5500.00,  500.00,  500.00, 14000.00, 1500.00, 2500.00, 1000.00, 14000.00, 4500.00, 60),
        (DATE '2026-07-23', 6000.00, 1000.00,  500.00, 15000.00, 1500.00, 2500.00, 1500.00, 15000.00, 5000.00, 65),
        (DATE '2026-07-24', 7000.00, 1000.00, 1000.00, 18000.00, 2000.00, 3000.00, 2000.00, 18000.00, 6000.00, 80),
        (DATE '2026-07-25', 8000.00, 1500.00, 1000.00, 20000.00, 2500.00, 3500.00, 2500.00, 20500.00, 6500.00, 90),
        (DATE '2026-07-26', 6500.00, 1000.00,  500.00, 16000.00, 2000.00, 3000.00, 1500.00, 16000.00, 5500.00, 75)
)
INSERT INTO finance.ventas (
    sucursal_id, fecha, monto_neto, fuente, referencia, es_demo, registrada_por,
    efectivo, rappi, uber, visa, amex,
    venta_otro, venta_aplicaciones, venta_alimentos, venta_bebidas, visitas
)
SELECT
    s.id,
    d.fecha,
    (d.efectivo + d.rappi + d.uber + d.visa + d.amex)::numeric(14,2),
    'demo', 'SEMANA-DEMO-S30-2026', true, 'migracion-011-demo',
    d.efectivo, d.rappi, d.uber, d.visa, d.amex,
    d.venta_otro, d.venta_aplicaciones, d.venta_alimentos, d.venta_bebidas, d.visitas
FROM datos d
JOIN catalog.sucursales s ON s.clave = 'DEMO-A'
ON CONFLICT (sucursal_id, fecha) DO UPDATE SET
    monto_neto = EXCLUDED.monto_neto,
    fuente = EXCLUDED.fuente,
    referencia = EXCLUDED.referencia,
    es_demo = true,
    registrada_por = EXCLUDED.registrada_por,
    efectivo = EXCLUDED.efectivo,
    rappi = EXCLUDED.rappi,
    uber = EXCLUDED.uber,
    visa = EXCLUDED.visa,
    amex = EXCLUDED.amex,
    venta_otro = EXCLUDED.venta_otro,
    venta_aplicaciones = EXCLUDED.venta_aplicaciones,
    venta_alimentos = EXCLUDED.venta_alimentos,
    venta_bebidas = EXCLUDED.venta_bebidas,
    visitas = EXCLUDED.visitas,
    actualizada_en = now();

INSERT INTO catalog.subcategorias (categoria_id, clave, nombre, activa)
SELECT id, 'IMPREVISTOS', 'Imprevistos', true
FROM catalog.categorias WHERE clave = 'VARIABLES'
ON CONFLICT (categoria_id, clave) DO UPDATE
SET nombre = EXCLUDED.nombre, activa = true;

COMMIT;
