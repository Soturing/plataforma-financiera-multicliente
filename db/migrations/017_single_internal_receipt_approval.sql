BEGIN;

-- Los comprobantes que ya recibieron su primera autorización quedan aprobados.
UPDATE core.comprobantes_internos
SET estado = 'aprobado',
    aprobaciones_requeridas = 1,
    actualizado_en = now()
WHERE estado = 'pendiente_segunda_aprobacion';

UPDATE core.comprobantes_internos
SET aprobaciones_requeridas = 1,
    actualizado_en = now()
WHERE aprobaciones_requeridas <> 1;

ALTER TABLE core.comprobantes_internos
    DROP CONSTRAINT IF EXISTS comprobante_aprobaciones_validas;

ALTER TABLE core.comprobantes_internos
    ADD CONSTRAINT comprobante_aprobaciones_validas
    CHECK (aprobaciones_requeridas = 1);

ALTER TABLE core.comprobantes_internos
    DROP CONSTRAINT IF EXISTS comprobante_estado_valido;

ALTER TABLE core.comprobantes_internos
    ADD CONSTRAINT comprobante_estado_valido CHECK (
        estado IN ('pendiente_aprobacion', 'aprobado', 'rechazado', 'sustituido')
    );

COMMIT;
