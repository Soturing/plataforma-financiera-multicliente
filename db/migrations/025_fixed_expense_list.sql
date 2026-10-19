-- D-017: lista de gastos fijos con alta previa.
-- Un proveedor solo puede clasificarse como FIJOS si está activo en esta lista.
BEGIN;

CREATE TABLE IF NOT EXISTS catalog.gastos_fijos (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    proveedor_id uuid NOT NULL UNIQUE REFERENCES catalog.proveedores(id),
    subcategoria_id uuid REFERENCES catalog.subcategorias(id),
    periodicidad text CHECK (periodicidad IN ('una_semana', 'mensual', 'bimestral', 'personalizado')),
    activa boolean NOT NULL DEFAULT true,
    creado_por text NOT NULL,
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE audit.cambios_catalogo DROP CONSTRAINT IF EXISTS cambios_catalogo_entidad_check;
ALTER TABLE audit.cambios_catalogo
    ADD CONSTRAINT cambios_catalogo_entidad_check
    CHECK (entidad IN ('subcategoria', 'gasto_fijo'));

COMMIT;
