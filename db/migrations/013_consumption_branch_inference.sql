BEGIN;

CREATE TABLE IF NOT EXISTS catalog.productos_consumo (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    clave text NOT NULL UNIQUE,
    nombre text NOT NULL,
    aliases text[] NOT NULL DEFAULT '{}',
    activo boolean NOT NULL DEFAULT true,
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS catalog.reglas_consumo_sucursal (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    producto_id uuid NOT NULL REFERENCES catalog.productos_consumo(id),
    sucursal_id uuid NOT NULL REFERENCES catalog.sucursales(id),
    proveedor_id uuid REFERENCES catalog.proveedores(id),
    peso smallint NOT NULL CHECK (peso BETWEEN -100 AND 100),
    activa boolean NOT NULL DEFAULT true,
    version integer NOT NULL DEFAULT 1,
    creada_por text NOT NULL DEFAULT 'migracion-013',
    creada_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT (producto_id, sucursal_id, proveedor_id)
);

CREATE TABLE IF NOT EXISTS audit.inferencias_sucursal (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    factura_id uuid NOT NULL REFERENCES core.facturas(id) ON DELETE CASCADE,
    ocr_resultado_id uuid REFERENCES ocr.resultados(id) ON DELETE SET NULL,
    proveedor_id uuid REFERENCES catalog.proveedores(id),
    metodo text NOT NULL CHECK (metodo IN ('receptor', 'consumo')),
    sucursal_sugerida_id uuid REFERENCES catalog.sucursales(id),
    confianza numeric(5,4) NOT NULL CHECK (confianza BETWEEN 0 AND 1),
    nivel text NOT NULL CHECK (nivel IN ('alta', 'media', 'baja')),
    puntajes jsonb NOT NULL DEFAULT '[]'::jsonb,
    evidencias jsonb NOT NULL DEFAULT '[]'::jsonb,
    aplicada boolean NOT NULL DEFAULT false,
    sucursal_confirmada_id uuid REFERENCES catalog.sucursales(id),
    confirmada_por text,
    confirmada_en timestamptz,
    creada_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE (factura_id, ocr_resultado_id, metodo)
);

CREATE INDEX IF NOT EXISTS inferencias_sucursal_factura_idx
    ON audit.inferencias_sucursal (factura_id, creada_en DESC);

INSERT INTO catalog.productos_consumo (clave, nombre, aliases) VALUES
    ('FILETE', 'Filete', ARRAY['FILETE', 'FILETE DE RES']),
    ('SIRLOIN', 'Sirloin', ARRAY['SIRLOIN']),
    ('COSTILLA', 'Costilla', ARRAY['COSTILLA', 'COSTILLA DE RES']),
    ('TORERITA', 'Torerita', ARRAY['TORERITA', 'TORERITAS']),
    ('PULPA_NEGRA', 'Pulpa negra', ARRAY['PULPA NEGRA']),
    ('TOP_SIRLOIN', 'Top sirloin', ARRAY['TOP SIRLOIN', 'TOP SIRL']),
    ('DIEZMILLO', 'Diezmillo', ARRAY['DIEZMILLO', 'DIEZM']),
    ('RIB_EYE', 'Rib eye', ARRAY['RIB EYE', 'RIBEYE', 'RIB-EYE'])
ON CONFLICT (clave) DO UPDATE SET
    nombre = EXCLUDED.nombre,
    aliases = EXCLUDED.aliases,
    activo = true,
    actualizado_en = now();

WITH reglas(producto, sucursal, peso) AS (
    VALUES
        ('FILETE', 'DEMO-A', 40),
        ('COSTILLA', 'DEMO-A', 45),
        ('TORERITA', 'DEMO-A', 60),
        ('SIRLOIN', 'DEMO-A', 8),
        ('PULPA_NEGRA', 'DEMO-C', 60),
        ('TOP_SIRLOIN', 'DEMO-C', 45),
        ('DIEZMILLO', 'DEMO-C', 15),
        ('RIB_EYE', 'DEMO-B', 60),
        ('DIEZMILLO', 'DEMO-B', 15),
        ('SIRLOIN', 'DEMO-B', 8)
)
INSERT INTO catalog.reglas_consumo_sucursal (
    producto_id, sucursal_id, proveedor_id, peso, activa, version, creada_por
)
SELECT p.id, s.id, NULL, r.peso, true, 1, 'fixture-reglas-demo'
FROM reglas r
JOIN catalog.productos_consumo p ON p.clave = r.producto
JOIN catalog.sucursales s ON s.clave = r.sucursal
ON CONFLICT (producto_id, sucursal_id, proveedor_id) DO UPDATE SET
    peso = EXCLUDED.peso,
    activa = true,
    version = catalog.reglas_consumo_sucursal.version + 1,
    creada_por = EXCLUDED.creada_por,
    creada_en = now();

COMMIT;
