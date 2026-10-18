-- Fase 5 (D-016, D-024): RLS forzado por tenant y por sucursal dentro de la base del cliente.
--
-- Cada conexión declara:
--   app.tenant      clave del tenant que espera (debe coincidir con la identidad de esta base)
--   app.sucursales  '*' (todas) o lista de UUID de catalog.sucursales separados por coma
-- Sin esas variables, la conexión no ve ni escribe ninguna fila: falla cerrada.
--
-- Las cuentas: tenant_owner es propietaria (sólo migraciones); tenant_runtime es la
-- de la aplicación, sin propiedad, sin SUPERUSER ni BYPASSRLS (arquitectura-aislamiento §8).
-- Con FORCE, las políticas también aplican a la propietaria, por eso las vistas de
-- analytics (propiedad de tenant_owner) quedan filtradas igual que las tablas.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenant_runtime') THEN
        CREATE ROLE tenant_runtime NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
END $$;

CREATE SCHEMA seguridad;

-- Identidad única de esta base: el aprovisionamiento escribe la clave del tenant.
CREATE TABLE seguridad.identidad_tenant (
    unico boolean PRIMARY KEY DEFAULT true CHECK (unico),
    tenant_clave text NOT NULL CHECK (tenant_clave ~ '^[A-Z0-9-]{2,40}$'),
    registrado_en timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION seguridad.tenant_correcto() RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT EXISTS (
        SELECT 1 FROM seguridad.identidad_tenant
        WHERE tenant_clave = current_setting('app.tenant', true)
    )
$$;

CREATE FUNCTION seguridad.todas_las_sucursales() RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT coalesce(current_setting('app.sucursales', true), '') = '*'
$$;

CREATE FUNCTION seguridad.sucursal_visible(s uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT seguridad.todas_las_sucursales()
        OR (s IS NOT NULL AND s = ANY (
            string_to_array(nullif(nullif(current_setting('app.sucursales', true), ''), '*'), ',')::uuid[]
        ))
$$;

-- Una fila ligada a una factura es visible si la factura lo es (la consulta a
-- core.facturas ya pasa por su propia política de sucursal).
CREATE FUNCTION seguridad.factura_visible(f uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT f IS NULL OR EXISTS (SELECT 1 FROM core.facturas x WHERE x.id = f)
$$;

CREATE FUNCTION seguridad.comprobante_visible(c uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT c IS NULL OR EXISTS (SELECT 1 FROM core.comprobantes_internos x WHERE x.id = c)
$$;

-- Aplica ENABLE + FORCE y una política para todos los comandos.
CREATE FUNCTION seguridad.proteger(tabla regclass, condicion text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', tabla);
    EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', tabla);
    EXECUTE format('DROP POLICY IF EXISTS alcance ON %s', tabla);
    EXECUTE format(
        'CREATE POLICY alcance ON %s USING (seguridad.tenant_correcto() AND (%s)) WITH CHECK (seguridad.tenant_correcto() AND (%s))',
        tabla, condicion, condicion
    );
END $$;

-- Sucursal propia de la fila
SELECT seguridad.proteger(t::regclass, 'seguridad.sucursal_visible(sucursal_id)') FROM unnest(ARRAY[
    'core.facturas', 'core.facturas_finales', 'core.lotes_carga', 'core.comprobantes_internos',
    'core.comprobante_distribuciones', 'finance.ventas', 'finance.nomina_semanal', 'finance.comision_parametros',
    'finance.comision_cierres', 'finance.parametros_equilibrio', 'finance.provisiones_fijas',
    'catalog.reglas_consumo_sucursal'
]) AS t;

SELECT seguridad.proteger('catalog.sucursales', 'seguridad.sucursal_visible(id)');

-- Sucursal heredada de la factura
SELECT seguridad.proteger(t::regclass, 'seguridad.factura_visible(factura_id)') FROM unnest(ARRAY[
    'ai.interpretaciones', 'ocr.resultados', 'core.validaciones', 'core.revisiones', 'core.trabajos_ocr',
    'core.clasificaciones_documentales', 'audit.correcciones', 'audit.aprendizajes', 'audit.inferencias_sucursal'
]) AS t;

SELECT seguridad.proteger('core.documentos_duplicados', 'seguridad.factura_visible(factura_duplicada_id)');
SELECT seguridad.proteger('core.documentos_continuacion', 'seguridad.factura_visible(factura_principal_id)');
SELECT seguridad.proteger('finance.periodificaciones_gasto',
    'seguridad.factura_visible(factura_id) AND seguridad.comprobante_visible(comprobante_id)');
SELECT seguridad.proteger('finance.periodificacion_semanas',
    'EXISTS (SELECT 1 FROM finance.periodificaciones_gasto p WHERE p.id = periodificacion_id)');

-- Documentos eliminados: la factura ya no existe; sólo quien ve todas las sucursales los consulta.
ALTER TABLE audit.documentos_eliminados ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit.documentos_eliminados FORCE ROW LEVEL SECURITY;
CREATE POLICY consulta ON audit.documentos_eliminados FOR SELECT
    USING (seguridad.tenant_correcto() AND seguridad.todas_las_sucursales());
CREATE POLICY registro ON audit.documentos_eliminados FOR INSERT
    WITH CHECK (seguridad.tenant_correcto());

-- Todo lo demás (catálogos del grupo, cola técnica, etc.): sólo la barrera de tenant.
DO $$
DECLARE
    t record;
BEGIN
    FOR t IN
        SELECT c.oid::regclass AS tabla
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p') AND NOT c.relrowsecurity
          AND n.nspname IN ('ai', 'audit', 'catalog', 'core', 'finance', 'ocr', 'analytics')
    LOOP
        PERFORM seguridad.proteger(t.tabla, 'true');
    END LOOP;
END $$;

-- Permisos de la cuenta de la aplicación.
DO $$
DECLARE
    esquema text;
BEGIN
    FOREACH esquema IN ARRAY ARRAY['ai', 'audit', 'catalog', 'core', 'finance', 'ocr', 'analytics', 'seguridad'] LOOP
        IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = esquema) THEN
            EXECUTE format('GRANT USAGE ON SCHEMA %I TO tenant_runtime', esquema);
            EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO tenant_runtime', esquema);
            EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO tenant_runtime', esquema);
            EXECUTE format('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA %I TO tenant_runtime', esquema);
        END IF;
    END LOOP;
    FOREACH esquema IN ARRAY ARRAY['ai', 'catalog', 'core', 'finance', 'ocr'] LOOP
        EXECUTE format('GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO tenant_runtime', esquema);
    END LOOP;
END $$;

-- Auditoría del negocio: sólo anexar (excepto confirmar la sucursal inferida).
GRANT INSERT ON ALL TABLES IN SCHEMA audit TO tenant_runtime;
GRANT UPDATE ON audit.inferencias_sucursal TO tenant_runtime;
REVOKE INSERT, UPDATE, DELETE ON seguridad.identidad_tenant FROM tenant_runtime;
REVOKE EXECUTE ON FUNCTION seguridad.proteger(regclass, text) FROM tenant_runtime, PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Tablas futuras creadas por la propietaria: la app recibe los mismos permisos.
-- (Su política RLS se agrega en la migración que las crea; una prueba lo exige.)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenant_owner') THEN
        ALTER DEFAULT PRIVILEGES FOR ROLE tenant_owner GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tenant_runtime;
        ALTER DEFAULT PRIVILEGES FOR ROLE tenant_owner GRANT USAGE, SELECT ON SEQUENCES TO tenant_runtime;
        ALTER DEFAULT PRIVILEGES FOR ROLE tenant_owner GRANT EXECUTE ON FUNCTIONS TO tenant_runtime;
    END IF;
END $$;
