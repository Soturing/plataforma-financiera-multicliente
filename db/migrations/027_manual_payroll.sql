-- D-017: nómina capturada a mano por semana ISO y sucursal.
BEGIN;

CREATE TABLE IF NOT EXISTS finance.nomina_semanal (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sucursal_id uuid NOT NULL REFERENCES catalog.sucursales(id),
    anio_iso smallint NOT NULL CHECK (anio_iso BETWEEN 2000 AND 2100),
    semana_iso smallint NOT NULL CHECK (semana_iso BETWEEN 1 AND 53),
    monto numeric(14,2) NOT NULL CHECK (monto >= 0),
    nota text,
    registrada_por text NOT NULL,
    actualizada_en timestamptz NOT NULL DEFAULT now(),
    UNIQUE (sucursal_id, anio_iso, semana_iso)
);

COMMIT;
