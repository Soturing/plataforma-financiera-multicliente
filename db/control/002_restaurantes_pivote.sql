-- D-024: alcance por restaurante o por sucursal mediante tablas pivote.
-- Sustituye el arreglo `asignaciones.sucursales` por relaciones con integridad.

CREATE TABLE control.restaurantes (
    tenant_id uuid NOT NULL REFERENCES control.tenants(id),
    clave text NOT NULL,
    nombre text NOT NULL,
    data_plane_id uuid NOT NULL,          -- id en catalog.restaurantes de la base del cliente
    activo boolean NOT NULL DEFAULT true,
    PRIMARY KEY (tenant_id, clave)
);

ALTER TABLE control.sucursales ADD COLUMN restaurante_clave text;
ALTER TABLE control.sucursales ADD CONSTRAINT sucursales_restaurante
    FOREIGN KEY (tenant_id, restaurante_clave) REFERENCES control.restaurantes (tenant_id, clave);

CREATE TABLE control.asignacion_restaurantes (
    asignacion_id uuid NOT NULL REFERENCES control.asignaciones(id) ON DELETE CASCADE,
    tenant_id uuid NOT NULL,
    restaurante_clave text NOT NULL,
    PRIMARY KEY (asignacion_id, restaurante_clave),
    FOREIGN KEY (tenant_id, restaurante_clave) REFERENCES control.restaurantes (tenant_id, clave)
);

CREATE TABLE control.asignacion_sucursales (
    asignacion_id uuid NOT NULL REFERENCES control.asignaciones(id) ON DELETE CASCADE,
    tenant_id uuid NOT NULL,
    sucursal_clave text NOT NULL,
    PRIMARY KEY (asignacion_id, sucursal_clave),
    FOREIGN KEY (tenant_id, sucursal_clave) REFERENCES control.sucursales (tenant_id, clave)
);

-- El alcance sólo puede apuntar al cliente de la propia asignación.
CREATE FUNCTION control.validar_alcance() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM control.asignaciones a WHERE a.id = NEW.asignacion_id AND a.tenant_id = NEW.tenant_id
    ) THEN
        RAISE EXCEPTION 'El alcance debe pertenecer al cliente de la asignación';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER asignacion_restaurantes_validar BEFORE INSERT OR UPDATE ON control.asignacion_restaurantes
    FOR EACH ROW EXECUTE FUNCTION control.validar_alcance();
CREATE TRIGGER asignacion_sucursales_validar BEFORE INSERT OR UPDATE ON control.asignacion_sucursales
    FOR EACH ROW EXECUTE FUNCTION control.validar_alcance();

-- Conserva el alcance ya asignado y elimina el arreglo.
INSERT INTO control.asignacion_sucursales (asignacion_id, tenant_id, sucursal_clave)
SELECT a.id, a.tenant_id, s FROM control.asignaciones a, unnest(a.sucursales) AS s
WHERE a.sucursales IS NOT NULL AND a.tenant_id IS NOT NULL
ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION control.validar_asignacion() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    r control.roles;
BEGIN
    SELECT * INTO r FROM control.roles WHERE codigo = NEW.rol;
    IF NEW.tenant_id IS NULL AND NOT r.global THEN
        RAISE EXCEPTION 'El rol % requiere un cliente', NEW.rol;
    END IF;
    IF NOT r.multicliente AND EXISTS (
        SELECT 1 FROM control.asignaciones a
        WHERE a.identidad_id = NEW.identidad_id AND a.id <> NEW.id AND a.estado = 'ACTIVA'
          AND a.tenant_id IS DISTINCT FROM NEW.tenant_id
    ) THEN
        RAISE EXCEPTION 'Los usuarios del cliente sólo pueden pertenecer a un cliente';
    END IF;
    IF NEW.modulos IS NOT NULL AND EXISTS (
        SELECT 1 FROM unnest(NEW.modulos) m WHERE m NOT IN (SELECT codigo FROM control.modulos)
    ) THEN
        RAISE EXCEPTION 'Módulo desconocido en la asignación';
    END IF;
    RETURN NEW;
END $$;

ALTER TABLE control.asignaciones DROP COLUMN sucursales;

-- Alcance efectivo: NULL = todas las sucursales; si hay restaurantes o sucursales
-- asignados, la unión de las sucursales directas y las de esos restaurantes.
CREATE VIEW control.alcance_asignacion AS
SELECT a.id AS asignacion_id,
       CASE
           WHEN NOT EXISTS (SELECT 1 FROM control.asignacion_restaurantes ar WHERE ar.asignacion_id = a.id)
            AND NOT EXISTS (SELECT 1 FROM control.asignacion_sucursales asu WHERE asu.asignacion_id = a.id)
           THEN NULL
           ELSE ARRAY(
               SELECT asu.sucursal_clave FROM control.asignacion_sucursales asu WHERE asu.asignacion_id = a.id
               UNION
               SELECT s.clave FROM control.asignacion_restaurantes ar
               JOIN control.sucursales s ON s.tenant_id = ar.tenant_id AND s.restaurante_clave = ar.restaurante_clave
               WHERE ar.asignacion_id = a.id
               ORDER BY 1
           )
       END AS sucursales,
       ARRAY(
           SELECT ar.restaurante_clave FROM control.asignacion_restaurantes ar
           WHERE ar.asignacion_id = a.id ORDER BY 1
       ) AS restaurantes
FROM control.asignaciones a;

GRANT SELECT, INSERT, UPDATE ON control.restaurantes TO control_app;
GRANT SELECT, INSERT, DELETE ON control.asignacion_restaurantes, control.asignacion_sucursales TO control_app;
GRANT SELECT ON control.alcance_asignacion TO control_app;
