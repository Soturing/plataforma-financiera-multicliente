-- Páginas de una misma factura: una página sin totales (continuación) queda ligada a la página principal
-- del mismo proveedor y folio dentro del lote. La continuación sale de la bandeja; "separar" la devuelve.
BEGIN;

CREATE TABLE IF NOT EXISTS core.documentos_continuacion (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    factura_principal_id uuid NOT NULL REFERENCES core.facturas(id) ON DELETE CASCADE,
    factura_continuacion_id uuid NOT NULL UNIQUE REFERENCES core.facturas(id) ON DELETE CASCADE,
    criterio text NOT NULL CHECK (criterio IN ('folio')),
    valor_coincidente text NOT NULL,
    estado text NOT NULL DEFAULT 'activa' CHECK (estado IN ('activa', 'separada')),
    detectado_en timestamptz NOT NULL DEFAULT now(),
    detectado_por text NOT NULL DEFAULT 'sistema',
    resuelto_en timestamptz,
    resuelto_por text,
    CHECK (factura_principal_id <> factura_continuacion_id),
    CHECK ((estado = 'activa' AND resuelto_en IS NULL AND resuelto_por IS NULL)
        OR (estado = 'separada' AND resuelto_en IS NOT NULL AND resuelto_por IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS documentos_continuacion_principal_idx
    ON core.documentos_continuacion (factura_principal_id) WHERE estado = 'activa';

COMMIT;
