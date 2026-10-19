-- Roadmap §3.8.1: la auditoría del data plane no se pierde ni se reescribe.
--
-- 1. Una factura (o revisión) con correcciones ya no se puede borrar: antes el
--    ON DELETE CASCADE borraba su historial de correcciones (decisión del
--    2026-10-19: impedir el borrado).
-- 2. audit.correcciones, audit.cambios_catalogo y audit.documentos_eliminados son
--    de sólo anexado también para tenant_owner (los permisos ya lo impedían a
--    tenant_runtime). audit.aprendizajes no admite DELETE pero sí el UPDATE que
--    hace su ON DELETE SET NULL al borrar un proveedor o una factura.
--    audit.inferencias_sucursal queda fuera: la app confirma la sucursal con
--    UPDATE y se borra con las facturas pendientes.
-- 3. Única salida: la propietaria de la tabla declara `SET LOCAL audit.purga = 'on'`
--    (limpieza de pruebas y, más adelante, la política de retención). Protege contra
--    cambios accidentales; quien es dueña de la tabla puede quitar el trigger igual.

ALTER TABLE audit.correcciones
    DROP CONSTRAINT correcciones_revision_id_fkey,
    DROP CONSTRAINT correcciones_factura_id_fkey,
    ADD CONSTRAINT correcciones_revision_id_fkey
        FOREIGN KEY (revision_id) REFERENCES core.revisiones(id) ON DELETE RESTRICT,
    ADD CONSTRAINT correcciones_factura_id_fkey
        FOREIGN KEY (factura_id) REFERENCES core.facturas(id) ON DELETE RESTRICT;

CREATE FUNCTION audit.rechazar_cambio() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF current_setting('audit.purga', true) = 'on' AND EXISTS (
        SELECT 1 FROM pg_class
        WHERE oid = TG_RELID AND pg_has_role(current_user, relowner, 'USAGE')
    ) THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    RAISE EXCEPTION 'La auditoría es de sólo anexado: % no permitido en %.%', TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END $$;

DO $$
DECLARE
    tabla text;
BEGIN
    FOREACH tabla IN ARRAY ARRAY['audit.correcciones', 'audit.cambios_catalogo', 'audit.documentos_eliminados'] LOOP
        EXECUTE format(
            'CREATE TRIGGER solo_anexado BEFORE UPDATE OR DELETE ON %s FOR EACH ROW EXECUTE FUNCTION audit.rechazar_cambio()',
            tabla);
        EXECUTE format(
            'CREATE TRIGGER solo_anexado_truncate BEFORE TRUNCATE ON %s FOR EACH STATEMENT EXECUTE FUNCTION audit.rechazar_cambio()',
            tabla);
    END LOOP;
END $$;

CREATE TRIGGER solo_anexado BEFORE DELETE ON audit.aprendizajes
    FOR EACH ROW EXECUTE FUNCTION audit.rechazar_cambio();
CREATE TRIGGER solo_anexado_truncate BEFORE TRUNCATE ON audit.aprendizajes
    FOR EACH STATEMENT EXECUTE FUNCTION audit.rechazar_cambio();
