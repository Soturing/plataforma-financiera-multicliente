BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS ocr;
CREATE SCHEMA IF NOT EXISTS ai;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TYPE core.estado_factura AS ENUM (
    'recibida', 'ocr_procesando', 'ocr_completado', 'ia_procesando',
    'ia_completada', 'validando', 'requiere_revision', 'aprobada',
    'rechazada', 'error'
);

CREATE TYPE core.canal_ingreso AS ENUM ('web', 'whatsapp', 'api', 'carga_masiva');
CREATE TYPE core.decision_revision AS ENUM ('aprobada', 'corregida_y_aprobada', 'rechazada');
CREATE TYPE core.severidad_validacion AS ENUM ('informativa', 'advertencia', 'error');

CREATE TABLE catalog.sucursales (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    clave text NOT NULL UNIQUE,
    nombre text NOT NULL,
    restaurante text NOT NULL,
    razon_social text,
    rfc text,
    aliases text[] NOT NULL DEFAULT '{}',
    zona_horaria text NOT NULL DEFAULT 'America/Mexico_City',
    activa boolean NOT NULL DEFAULT true,
    creada_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE catalog.proveedores (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rfc text,
    nombre_legal text NOT NULL,
    nombre_normalizado text NOT NULL,
    activo boolean NOT NULL DEFAULT true,
    creado_en timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT proveedores_rfc_formato CHECK (rfc IS NULL OR rfc ~ '^[A-Z&Ñ]{3,4}[0-9]{6}[A-Z0-9]{3}$')
);

CREATE UNIQUE INDEX proveedores_rfc_unico
    ON catalog.proveedores (rfc) WHERE rfc IS NOT NULL;
CREATE INDEX proveedores_nombre_normalizado_idx
    ON catalog.proveedores (lower(nombre_normalizado));

CREATE TABLE catalog.categorias (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    clave text NOT NULL UNIQUE,
    nombre text NOT NULL UNIQUE,
    activa boolean NOT NULL DEFAULT true,
    orden smallint NOT NULL DEFAULT 0
);

CREATE TABLE catalog.subcategorias (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    categoria_id uuid NOT NULL REFERENCES catalog.categorias(id),
    clave text NOT NULL,
    nombre text NOT NULL,
    activa boolean NOT NULL DEFAULT true,
    UNIQUE (categoria_id, clave),
    UNIQUE (categoria_id, nombre),
    UNIQUE (id, categoria_id)
);

CREATE TABLE catalog.centros_costo (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    clave text NOT NULL UNIQUE,
    nombre text NOT NULL UNIQUE,
    activo boolean NOT NULL DEFAULT true
);

CREATE TABLE catalog.reglas_clasificacion (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre text NOT NULL,
    prioridad integer NOT NULL DEFAULT 100,
    proveedor_id uuid REFERENCES catalog.proveedores(id),
    patron_texto text,
    categoria_id uuid NOT NULL REFERENCES catalog.categorias(id),
    subcategoria_id uuid,
    centro_costo_id uuid REFERENCES catalog.centros_costo(id),
    activa boolean NOT NULL DEFAULT true,
    version integer NOT NULL DEFAULT 1,
    creada_en timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (subcategoria_id, categoria_id)
        REFERENCES catalog.subcategorias(id, categoria_id),
    CHECK (proveedor_id IS NOT NULL OR patron_texto IS NOT NULL)
);

CREATE TABLE core.facturas (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sucursal_id uuid NOT NULL REFERENCES catalog.sucursales(id),
    canal core.canal_ingreso NOT NULL DEFAULT 'web',
    estado core.estado_factura NOT NULL DEFAULT 'recibida',
    archivo_url text NOT NULL,
    archivo_nombre text NOT NULL,
    archivo_mime text NOT NULL,
    archivo_sha256 char(64) NOT NULL,
    recibida_en timestamptz NOT NULL DEFAULT now(),
    creada_por text NOT NULL,
    actualizada_en timestamptz NOT NULL DEFAULT now(),
    error_codigo text,
    error_detalle text
    , sucursal_origen text NOT NULL DEFAULT 'carga_manual'
    , sucursal_deteccion jsonb
);

CREATE INDEX facturas_estado_recibida_idx ON core.facturas (estado, recibida_en);
CREATE INDEX facturas_sucursal_recibida_idx ON core.facturas (sucursal_id, recibida_en DESC);
CREATE INDEX facturas_archivo_sha256_idx ON core.facturas (archivo_sha256);

CREATE TABLE ocr.resultados (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    factura_id uuid NOT NULL REFERENCES core.facturas(id) ON DELETE CASCADE,
    version integer NOT NULL,
    proveedor_ocr text NOT NULL,
    modelo_ocr text NOT NULL,
    texto_raw text NOT NULL,
    json_raw jsonb NOT NULL,
    confianza numeric(5,4),
    procesado_en timestamptz NOT NULL DEFAULT now(),
    duracion_ms integer,
    UNIQUE (factura_id, version),
    CHECK (confianza IS NULL OR confianza BETWEEN 0 AND 1),
    CHECK (duracion_ms IS NULL OR duracion_ms >= 0)
);

CREATE INDEX resultados_ocr_factura_idx ON ocr.resultados (factura_id, version DESC);

CREATE TABLE ai.interpretaciones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    factura_id uuid NOT NULL REFERENCES core.facturas(id) ON DELETE CASCADE,
    ocr_resultado_id uuid NOT NULL REFERENCES ocr.resultados(id),
    version integer NOT NULL,
    modelo_ia text NOT NULL,
    reglas_version text NOT NULL,
    proveedor_id uuid REFERENCES catalog.proveedores(id),
    proveedor_propuesto text,
    rfc_emisor text,
    uuid_fiscal uuid,
    serie text,
    folio text,
    fecha_emision date,
    moneda char(3) NOT NULL DEFAULT 'MXN',
    metodo_pago text,
    forma_pago text,
    subtotal numeric(14,2),
    descuento numeric(14,2) NOT NULL DEFAULT 0,
    iva numeric(14,2) NOT NULL DEFAULT 0,
    otros_impuestos numeric(14,2) NOT NULL DEFAULT 0,
    total numeric(14,2),
    categoria_id uuid REFERENCES catalog.categorias(id),
    subcategoria_id uuid,
    centro_costo_id uuid REFERENCES catalog.centros_costo(id),
    confianza numeric(5,4),
    observaciones text,
    salida_json jsonb NOT NULL,
    interpretada_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE (factura_id, version),
    FOREIGN KEY (subcategoria_id, categoria_id)
        REFERENCES catalog.subcategorias(id, categoria_id),
    CHECK (confianza IS NULL OR confianza BETWEEN 0 AND 1),
    CHECK (subtotal IS NULL OR subtotal >= 0),
    CHECK (descuento >= 0 AND iva >= 0 AND otros_impuestos >= 0),
    CHECK (total IS NULL OR total > 0)
);

CREATE INDEX interpretaciones_uuid_fiscal_idx
    ON ai.interpretaciones (uuid_fiscal) WHERE uuid_fiscal IS NOT NULL;
CREATE INDEX interpretaciones_factura_idx ON ai.interpretaciones (factura_id, version DESC);

CREATE TABLE core.validaciones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    factura_id uuid NOT NULL REFERENCES core.facturas(id) ON DELETE CASCADE,
    interpretacion_id uuid NOT NULL REFERENCES ai.interpretaciones(id) ON DELETE CASCADE,
    codigo text NOT NULL,
    severidad core.severidad_validacion NOT NULL,
    aprobada boolean NOT NULL,
    campo text,
    mensaje text NOT NULL,
    esperado jsonb,
    observado jsonb,
    ejecutada_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE (interpretacion_id, codigo)
);

CREATE INDEX validaciones_pendientes_idx
    ON core.validaciones (factura_id, severidad) WHERE aprobada = false;

CREATE TABLE core.revisiones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    factura_id uuid NOT NULL REFERENCES core.facturas(id) ON DELETE CASCADE,
    interpretacion_id uuid NOT NULL REFERENCES ai.interpretaciones(id),
    decision core.decision_revision NOT NULL,
    revisada_por text NOT NULL,
    comentario text,
    iniciada_en timestamptz,
    decidida_en timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX revisiones_factura_idx ON core.revisiones (factura_id, decidida_en DESC);

CREATE TABLE audit.correcciones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    revision_id uuid NOT NULL REFERENCES core.revisiones(id) ON DELETE CASCADE,
    factura_id uuid NOT NULL REFERENCES core.facturas(id) ON DELETE CASCADE,
    campo text NOT NULL,
    valor_propuesto jsonb,
    valor_corregido jsonb NOT NULL,
    motivo text,
    corregido_por text NOT NULL,
    corregido_en timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX correcciones_factura_idx ON audit.correcciones (factura_id, corregido_en);
CREATE INDEX correcciones_campo_idx ON audit.correcciones (campo);

CREATE TABLE core.facturas_finales (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    factura_id uuid NOT NULL REFERENCES core.facturas(id),
    revision_id uuid NOT NULL REFERENCES core.revisiones(id),
    interpretacion_id uuid NOT NULL REFERENCES ai.interpretaciones(id),
    version integer NOT NULL DEFAULT 1,
    vigente boolean NOT NULL DEFAULT true,
    sucursal_id uuid NOT NULL REFERENCES catalog.sucursales(id),
    proveedor_id uuid NOT NULL REFERENCES catalog.proveedores(id),
    rfc_emisor text,
    uuid_fiscal uuid,
    serie text,
    folio text,
    fecha_emision date NOT NULL,
    moneda char(3) NOT NULL DEFAULT 'MXN',
    metodo_pago text,
    forma_pago text,
    subtotal numeric(14,2) NOT NULL,
    descuento numeric(14,2) NOT NULL DEFAULT 0,
    iva numeric(14,2) NOT NULL DEFAULT 0,
    otros_impuestos numeric(14,2) NOT NULL DEFAULT 0,
    total numeric(14,2) NOT NULL,
    categoria_id uuid NOT NULL REFERENCES catalog.categorias(id),
    subcategoria_id uuid,
    centro_costo_id uuid REFERENCES catalog.centros_costo(id),
    observaciones text,
    aprobada_por text NOT NULL,
    aprobada_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE (factura_id, version),
    FOREIGN KEY (subcategoria_id, categoria_id)
        REFERENCES catalog.subcategorias(id, categoria_id),
    CHECK (subtotal >= 0 AND descuento >= 0 AND iva >= 0 AND otros_impuestos >= 0),
    CHECK (total > 0)
);

CREATE UNIQUE INDEX facturas_finales_vigente_idx
    ON core.facturas_finales (factura_id) WHERE vigente;
CREATE UNIQUE INDEX facturas_finales_uuid_vigente_idx
    ON core.facturas_finales (uuid_fiscal) WHERE vigente AND uuid_fiscal IS NOT NULL;
CREATE INDEX facturas_finales_fecha_idx
    ON core.facturas_finales (fecha_emision, sucursal_id);

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
WHERE ff.vigente;

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
    COUNT(*) AS facturas,
    SUM(subtotal) AS subtotal,
    SUM(descuento) AS descuento,
    SUM(iva) AS iva,
    SUM(otros_impuestos) AS otros_impuestos,
    SUM(total) AS total
FROM analytics.facturas_consumo
GROUP BY
    anio_iso, semana_iso, restaurante, sucursal_clave, sucursal,
    categoria, subcategoria, moneda;

COMMIT;
