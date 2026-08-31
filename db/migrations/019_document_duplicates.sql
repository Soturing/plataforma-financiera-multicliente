BEGIN;

CREATE TABLE core.documentos_duplicados (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    factura_original_id uuid NOT NULL REFERENCES core.facturas(id),
    factura_duplicada_id uuid REFERENCES core.facturas(id),
    archivo_url text NOT NULL,
    archivo_nombre text NOT NULL,
    archivo_sha256 char(64),
    criterio text NOT NULL CHECK (criterio IN ('sha256', 'uuid_fiscal')),
    valor_coincidente text NOT NULL,
    estado text NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente', 'descartado')),
    detectado_en timestamptz NOT NULL DEFAULT now(),
    detectado_por text NOT NULL DEFAULT 'sistema',
    resuelto_en timestamptz,
    resuelto_por text,
    CHECK ((estado = 'pendiente' AND resuelto_en IS NULL AND resuelto_por IS NULL)
        OR (estado = 'descartado' AND resuelto_en IS NOT NULL AND resuelto_por IS NOT NULL))
);

CREATE UNIQUE INDEX documentos_duplicados_factura_criterio_idx
    ON core.documentos_duplicados (factura_duplicada_id, criterio)
    WHERE factura_duplicada_id IS NOT NULL AND estado = 'pendiente';
CREATE INDEX documentos_duplicados_estado_idx
    ON core.documentos_duplicados (estado, detectado_en DESC);

COMMIT;
