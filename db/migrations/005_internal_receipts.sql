ALTER TABLE catalog.proveedores
    ADD COLUMN IF NOT EXISTS es_informal boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS telefono text,
    ADD COLUMN IF NOT EXISTS giro text;

CREATE SEQUENCE IF NOT EXISTS core.comprobantes_internos_folio_seq;

CREATE TABLE IF NOT EXISTS core.comprobantes_internos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    folio text NOT NULL UNIQUE DEFAULT (
        'CI-' || EXTRACT(YEAR FROM CURRENT_DATE)::integer::text || '-' ||
        lpad(nextval('core.comprobantes_internos_folio_seq')::text, 6, '0')
    ),
    numero_documento text NOT NULL,
    numero_documento_origen text NOT NULL DEFAULT 'fecha',
    sucursal_id uuid NOT NULL REFERENCES catalog.sucursales(id),
    proveedor_id uuid NOT NULL REFERENCES catalog.proveedores(id),
    fecha_gasto date NOT NULL,
    concepto text NOT NULL,
    metodo_pago text NOT NULL,
    total numeric(14,2) NOT NULL,
    moneda char(3) NOT NULL DEFAULT 'MXN',
    categoria_id uuid NOT NULL REFERENCES catalog.categorias(id),
    subcategoria_id uuid,
    centro_costo_id uuid REFERENCES catalog.centros_costo(id),
    creado_por text NOT NULL,
    rol_creador text NOT NULL,
    firma_proveedor_nombre text,
    firma_proveedor_confirmada boolean NOT NULL DEFAULT false,
    firma_proveedor_en timestamptz,
    evidencia_url text,
    evidencia_nombre text,
    evidencia_mime text,
    evidencia_sha256 char(64),
    estado text NOT NULL,
    estado_fiscal text NOT NULL DEFAULT 'no_deducible',
    aprobaciones_requeridas smallint NOT NULL,
    primera_aprobacion_por text,
    primera_aprobacion_en timestamptz,
    primera_aprobacion_comentario text,
    segunda_aprobacion_por text,
    segunda_aprobacion_en timestamptz,
    segunda_aprobacion_comentario text,
    rechazado_por text,
    rechazado_en timestamptz,
    motivo_rechazo text,
    factura_final_reemplazo_id uuid REFERENCES core.facturas_finales(id),
    sustituido_en timestamptz,
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (subcategoria_id, categoria_id)
        REFERENCES catalog.subcategorias(id, categoria_id),
    CONSTRAINT comprobante_total_valido CHECK (total > 0 AND total <= 300000),
    CONSTRAINT comprobante_metodo_pago_valido CHECK (
        metodo_pago IN ('efectivo', 'transferencia', 'tarjeta', 'otro')
    ),
    CONSTRAINT comprobante_rol_valido CHECK (rol_creador IN ('gerente', 'capturista')),
    CONSTRAINT comprobante_estado_valido CHECK (
        estado IN ('pendiente_aprobacion', 'pendiente_segunda_aprobacion', 'aprobado', 'rechazado', 'sustituido')
    ),
    CONSTRAINT comprobante_estado_fiscal_valido CHECK (
        estado_fiscal IN ('no_deducible', 'pendiente_cfdi', 'con_cfdi')
    ),
    CONSTRAINT comprobante_aprobaciones_validas CHECK (aprobaciones_requeridas IN (1, 2)),
    CONSTRAINT comprobante_firma_efectivo CHECK (
        metodo_pago <> 'efectivo' OR
        (firma_proveedor_confirmada AND nullif(trim(firma_proveedor_nombre), '') IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS comprobantes_internos_estado_idx
    ON core.comprobantes_internos (estado, creado_en DESC);
CREATE INDEX IF NOT EXISTS comprobantes_internos_fecha_idx
    ON core.comprobantes_internos (fecha_gasto, sucursal_id);
CREATE INDEX IF NOT EXISTS comprobantes_internos_proveedor_idx
    ON core.comprobantes_internos (proveedor_id, fecha_gasto DESC);
CREATE INDEX IF NOT EXISTS comprobantes_internos_numero_idx
    ON core.comprobantes_internos (lower(numero_documento));

CREATE TABLE IF NOT EXISTS core.comprobante_distribuciones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    comprobante_id uuid NOT NULL REFERENCES core.comprobantes_internos(id) ON DELETE CASCADE,
    sucursal_id uuid NOT NULL REFERENCES catalog.sucursales(id),
    monto numeric(14,2) NOT NULL CHECK (monto > 0),
    creado_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE (comprobante_id, sucursal_id)
);

CREATE OR REPLACE VIEW analytics.movimientos_gasto AS
SELECT
    ff.id AS movimiento_id,
    'factura_fiscal'::text AS tipo_documento,
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
    'con_cfdi'::text AS estado_fiscal,
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

DROP VIEW IF EXISTS analytics.estado_resultados_semanal;
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
