BEGIN;

CREATE TYPE core.tipo_documento AS ENUM (
    'factura_fiscal',
    'nota_credito',
    'transferencia_bancaria',
    'pago_servicio',
    'sipare_imss',
    'comprobante_pago',
    'recibo',
    'desconocido'
);

CREATE TABLE core.clasificaciones_documentales (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    factura_id uuid NOT NULL REFERENCES core.facturas(id) ON DELETE CASCADE,
    version integer NOT NULL,
    tipo core.tipo_documento NOT NULL,
    confianza numeric(5,4) NOT NULL,
    clasificador text NOT NULL,
    reglas_version text NOT NULL,
    evidencia jsonb NOT NULL,
    clasificada_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE (factura_id, version),
    CHECK (confianza BETWEEN 0 AND 1)
);

CREATE INDEX clasificaciones_factura_idx
    ON core.clasificaciones_documentales (factura_id, version DESC);
CREATE INDEX clasificaciones_tipo_idx
    ON core.clasificaciones_documentales (tipo, clasificada_en DESC);

COMMIT;
