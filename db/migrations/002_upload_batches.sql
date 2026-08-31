BEGIN;

CREATE TYPE core.estado_lote AS ENUM ('procesando', 'listo', 'error');

CREATE TABLE core.lotes_carga (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sucursal_id uuid NOT NULL REFERENCES catalog.sucursales(id),
    estado core.estado_lote NOT NULL DEFAULT 'procesando',
    archivo_original_url text NOT NULL,
    archivo_original_nombre text NOT NULL,
    archivo_sha256 char(64) NOT NULL,
    total_paginas integer NOT NULL DEFAULT 0,
    creado_por text NOT NULL,
    creado_en timestamptz NOT NULL DEFAULT now(),
    completado_en timestamptz,
    error_detalle text,
    CHECK (total_paginas >= 0)
);

ALTER TABLE core.facturas
    ADD COLUMN lote_id uuid REFERENCES core.lotes_carga(id),
    ADD COLUMN pagina_origen integer;

ALTER TABLE core.facturas
    ADD CONSTRAINT facturas_pagina_origen_positiva
        CHECK (pagina_origen IS NULL OR pagina_origen > 0),
    ADD CONSTRAINT facturas_lote_pagina_coherentes
        CHECK ((lote_id IS NULL) = (pagina_origen IS NULL));

CREATE UNIQUE INDEX facturas_lote_pagina_idx
    ON core.facturas (lote_id, pagina_origen) WHERE lote_id IS NOT NULL;
CREATE INDEX lotes_carga_estado_idx
    ON core.lotes_carga (estado, creado_en DESC);

COMMIT;
