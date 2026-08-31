BEGIN;

ALTER TABLE core.comprobantes_internos
    DROP CONSTRAINT IF EXISTS comprobante_total_valido;

ALTER TABLE core.comprobantes_internos
    ADD CONSTRAINT comprobante_total_valido
    CHECK (total > 0 AND total <= 300000);

COMMIT;
