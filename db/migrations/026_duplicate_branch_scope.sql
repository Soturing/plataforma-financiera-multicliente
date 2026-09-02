BEGIN;

ALTER TABLE core.documentos_duplicados
    ADD COLUMN sucursal_id uuid REFERENCES catalog.sucursales(id);

UPDATE core.documentos_duplicados d
SET sucursal_id = COALESCE(
    (
        SELECT fd.sucursal_id
        FROM core.facturas fd
        WHERE fd.id = d.factura_duplicada_id
    ),
    (
        SELECT fo.sucursal_id
        FROM core.facturas fo
        WHERE fo.id = d.factura_original_id
    )
);

ALTER TABLE core.documentos_duplicados
    ALTER COLUMN sucursal_id SET NOT NULL;

CREATE INDEX documentos_duplicados_sucursal_estado_idx
    ON core.documentos_duplicados (tenant_id, sucursal_id, estado, detectado_en DESC);

COMMENT ON COLUMN core.documentos_duplicados.sucursal_id IS
    'Sucursal destino del archivo detectado; no implica permiso para revelar la factura original.';

COMMIT;
