-- D-024: dentro de un tenant (una administración), la jerarquía es
-- restaurante → sucursal. Hasta ahora el restaurante era texto libre en
-- catalog.sucursales; aquí se formaliza para poder asignar alcance por
-- restaurante completo y filtrar con integridad referencial.

CREATE TABLE catalog.restaurantes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    clave text NOT NULL UNIQUE CHECK (clave ~ '^[A-Z0-9-]{2,40}$'),
    nombre text NOT NULL,
    razon_social text,
    rfc text,
    activo boolean NOT NULL DEFAULT true,
    creado_en timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE catalog.sucursales ADD COLUMN restaurante_id uuid REFERENCES catalog.restaurantes(id);

-- Un restaurante por cada nombre distinto. POR-ASIGNAR no es una sucursal real
-- (bandeja de documentos sin sucursal) y queda sin restaurante.
INSERT INTO catalog.restaurantes (clave, nombre, razon_social, rfc, activo)
SELECT DISTINCT ON (upper(trim(s.restaurante)))
       left(trim(both '-' from regexp_replace(upper(trim(s.restaurante)), '[^A-Z0-9]+', '-', 'g')), 40),
       trim(s.restaurante),
       nullif(trim(s.razon_social), ''),
       nullif(trim(s.rfc), ''),
       bool_or(s.activa) OVER (PARTITION BY upper(trim(s.restaurante)))
FROM catalog.sucursales s
WHERE s.clave <> 'POR-ASIGNAR' AND nullif(trim(s.restaurante), '') IS NOT NULL
ORDER BY upper(trim(s.restaurante)), s.activa DESC, s.razon_social NULLS LAST
ON CONFLICT (clave) DO NOTHING;

UPDATE catalog.sucursales s
SET restaurante_id = r.id
FROM catalog.restaurantes r
WHERE s.clave <> 'POR-ASIGNAR'
  AND r.clave = left(trim(both '-' from regexp_replace(upper(trim(s.restaurante)), '[^A-Z0-9]+', '-', 'g')), 40);

CREATE INDEX sucursales_restaurante ON catalog.sucursales (restaurante_id);

COMMENT ON TABLE catalog.restaurantes IS
    'Restaurantes de la administración (tenant). Cada sucursal pertenece a uno; POR-ASIGNAR a ninguno.';
