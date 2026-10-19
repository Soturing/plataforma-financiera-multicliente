-- Razones sociales del propio grupo (los receptores de las facturas). El lector de documentos las usa
-- para no confundirlas con el proveedor. Complementan el RFC y la razón social de cada sucursal.
BEGIN;

CREATE TABLE IF NOT EXISTS catalog.entidades_propias (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre text NOT NULL,
    rfc text,
    activa boolean NOT NULL DEFAULT true,
    creado_por text NOT NULL,
    creado_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE (nombre)
);

CREATE UNIQUE INDEX IF NOT EXISTS entidades_propias_rfc_idx
    ON catalog.entidades_propias (rfc) WHERE rfc IS NOT NULL;

COMMIT;
