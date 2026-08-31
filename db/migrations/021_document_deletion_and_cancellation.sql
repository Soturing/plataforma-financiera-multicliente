BEGIN;

ALTER TYPE core.estado_factura ADD VALUE IF NOT EXISTS 'cancelada';
ALTER TYPE core.estado_lote ADD VALUE IF NOT EXISTS 'cancelado';

CREATE TABLE IF NOT EXISTS audit.documentos_eliminados (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    factura_id uuid NOT NULL,
    lote_id uuid,
    archivo_nombre text NOT NULL,
    estado_anterior text NOT NULL,
    archivo_url text NOT NULL,
    eliminado_por text NOT NULL,
    eliminado_en timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS documentos_eliminados_fecha_idx
    ON audit.documentos_eliminados (eliminado_en DESC);

COMMIT;
