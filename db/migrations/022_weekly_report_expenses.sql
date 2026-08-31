BEGIN;

ALTER TABLE core.comprobantes_internos
    ADD COLUMN IF NOT EXISTS origen text NOT NULL DEFAULT 'manual',
    ADD COLUMN IF NOT EXISTS referencia_origen text;

ALTER TABLE core.comprobantes_internos
    DROP CONSTRAINT IF EXISTS comprobante_firma_efectivo;

ALTER TABLE core.comprobantes_internos
    ADD CONSTRAINT comprobante_firma_efectivo CHECK (
        metodo_pago <> 'efectivo'
        OR origen = 'reporte_semanal'
        OR (firma_proveedor_confirmada AND nullif(trim(firma_proveedor_nombre), '') IS NOT NULL)
    );

CREATE UNIQUE INDEX IF NOT EXISTS comprobantes_reporte_semanal_referencia_idx
    ON core.comprobantes_internos (sucursal_id, referencia_origen)
    WHERE origen = 'reporte_semanal' AND referencia_origen IS NOT NULL;

COMMIT;
