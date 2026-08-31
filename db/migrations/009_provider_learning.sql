BEGIN;

ALTER TABLE catalog.proveedores
    ADD COLUMN IF NOT EXISTS nombre_comercial text;

CREATE TABLE IF NOT EXISTS catalog.proveedor_aliases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    proveedor_id uuid NOT NULL REFERENCES catalog.proveedores(id) ON DELETE CASCADE,
    alias text NOT NULL,
    alias_normalizado text NOT NULL,
    origen text NOT NULL DEFAULT 'revision_humana',
    confirmado boolean NOT NULL DEFAULT true,
    apariciones integer NOT NULL DEFAULT 1 CHECK (apariciones > 0),
    creado_por text NOT NULL,
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT proveedor_alias_origen_valido CHECK (
        origen IN ('revision_humana', 'importacion', 'administracion', 'ocr')
    ),
    CONSTRAINT proveedor_alias_no_vacio CHECK (
        nullif(trim(alias), '') IS NOT NULL
        AND nullif(trim(alias_normalizado), '') IS NOT NULL
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS proveedor_alias_normalizado_unico
    ON catalog.proveedor_aliases (alias_normalizado);
CREATE INDEX IF NOT EXISTS proveedor_alias_proveedor_idx
    ON catalog.proveedor_aliases (proveedor_id, actualizado_en DESC);

CREATE TABLE IF NOT EXISTS audit.aprendizajes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    factura_id uuid REFERENCES core.facturas(id) ON DELETE SET NULL,
    revision_id uuid REFERENCES core.revisiones(id) ON DELETE SET NULL,
    proveedor_id uuid REFERENCES catalog.proveedores(id) ON DELETE SET NULL,
    tipo text NOT NULL,
    entrada jsonb NOT NULL DEFAULT '{}'::jsonb,
    salida jsonb NOT NULL DEFAULT '{}'::jsonb,
    aplicada boolean NOT NULL DEFAULT true,
    registrado_por text NOT NULL,
    registrado_en timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT aprendizaje_tipo_valido CHECK (
        tipo IN ('alias_proveedor', 'regla_contable', 'importacion_catalogo')
    )
);

CREATE INDEX IF NOT EXISTS aprendizajes_factura_idx
    ON audit.aprendizajes (factura_id, registrado_en DESC);
CREATE INDEX IF NOT EXISTS aprendizajes_proveedor_idx
    ON audit.aprendizajes (proveedor_id, registrado_en DESC);

INSERT INTO catalog.sucursales (
    clave, nombre, restaurante, razon_social, aliases, activa
) VALUES (
    'POR-ASIGNAR', 'Por asignar', 'CEDIS / Por asignar',
    'DOCUMENTO PENDIENTE DE ASIGNACION', '{}', true
)
ON CONFLICT (clave) DO UPDATE SET
    nombre = EXCLUDED.nombre,
    restaurante = EXCLUDED.restaurante,
    razon_social = EXCLUDED.razon_social,
    activa = true;

CREATE OR REPLACE VIEW analytics.dataset_entrenamiento AS
SELECT
    f.id AS factura_id,
    f.archivo_nombre,
    o.proveedor_ocr,
    o.modelo_ocr,
    o.confianza AS confianza_ocr,
    i.proveedor_propuesto,
    p.nombre_normalizado AS proveedor_final,
    p.rfc AS proveedor_rfc,
    i.folio AS folio_propuesto,
    ff.folio AS folio_final,
    i.fecha_emision AS fecha_propuesta,
    ff.fecha_emision AS fecha_final,
    i.total AS total_propuesto,
    ff.total AS total_final,
    cp.clave AS categoria_propuesta,
    cf.clave AS categoria_final,
    sp.clave AS subcategoria_propuesta,
    sf.clave AS subcategoria_final,
    si.clave AS sucursal_propuesta,
    sff.clave AS sucursal_final,
    ff.tipo_documento::text,
    ff.aprobada_por,
    ff.aprobada_en,
    EXISTS (
        SELECT 1 FROM audit.correcciones ac WHERE ac.factura_id = f.id
    ) AS tuvo_correcciones
FROM core.facturas f
JOIN core.facturas_finales ff ON ff.factura_id = f.id AND ff.vigente
JOIN ai.interpretaciones i ON i.id = ff.interpretacion_id
JOIN ocr.resultados o ON o.id = i.ocr_resultado_id
JOIN catalog.proveedores p ON p.id = ff.proveedor_id
JOIN catalog.categorias cf ON cf.id = ff.categoria_id
LEFT JOIN catalog.categorias cp ON cp.id = i.categoria_id
LEFT JOIN catalog.subcategorias sp ON sp.id = i.subcategoria_id
LEFT JOIN catalog.subcategorias sf ON sf.id = ff.subcategoria_id
JOIN catalog.sucursales si ON si.id = f.sucursal_id
JOIN catalog.sucursales sff ON sff.id = ff.sucursal_id;

COMMIT;
