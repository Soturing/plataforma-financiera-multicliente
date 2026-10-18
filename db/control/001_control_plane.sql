-- Plano de control (D-016, D-019). Base separada de la de negocio: guarda
-- identidades, asignaciones, sesiones y auditoría de seguridad. Nunca guarda
-- información financiera ni documentos de clientes.
--
-- Se ejecuta como propietario (control_owner). La aplicación usa control_app,
-- que no es propietaria de nada y no puede modificar ni borrar la auditoría.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA control;

-- --------------------------------------------------------------------------
-- Catálogos (D-011, D-012)

CREATE TABLE control.roles (
    codigo text PRIMARY KEY,
    nombre text NOT NULL,
    global boolean NOT NULL,          -- puede tener alcance sobre todos los clientes
    privilegiado boolean NOT NULL,    -- llave física, sesión corta (ciclo-vida §5, §7)
    multicliente boolean NOT NULL     -- puede asignarse a varios clientes
);

INSERT INTO control.roles VALUES
    ('CONSULTORA_DIRECTOR',   'Director de la consultora',  true,  true,  true),
    ('CONSULTORA_SEGURIDAD',  'Administrador de seguridad', true,  true,  true),
    ('CONSULTORA_CAPTURISTA', 'Capturista',                 false, false, true),
    ('SOPORTE_TECNICO',       'Soporte técnico',            true,  false, true),
    ('CLIENTE_RESPONSABLE',   'Responsable del cliente',    false, false, false),
    ('CLIENTE_FINANZAS',      'Finanzas del cliente',       false, false, false),
    ('CLIENTE_OPERADOR',      'Operador de sucursal',       false, false, false),
    ('INTEGRACION_API',       'Integración API',            false, false, false);

CREATE TABLE control.modulos (
    codigo text PRIMARY KEY,
    nombre text NOT NULL
);

INSERT INTO control.modulos VALUES
    ('DOCUMENTOS',     'Documentos'),
    ('COMPROBANTES',   'Comprobantes internos'),
    ('PROVEEDORES',    'Proveedores'),
    ('CATALOGOS',      'Catálogos contables'),
    ('VENTAS',         'Ventas'),
    ('FINANZAS',       'Finanzas'),
    ('REPORTES',       'Reportes'),
    ('NOMINA',         'Nómina'),
    ('INVENTARIOS',    'Inventarios'),
    ('RECETAS',        'Recetas'),
    ('CLIENTES',       'Administración de clientes'),
    ('IDENTIDADES',    'Identidades y accesos'),
    ('AUDITORIA',      'Auditoría y seguridad'),
    ('INTEGRACIONES',  'Integraciones'),
    ('OPERACION',      'Operación técnica');

-- --------------------------------------------------------------------------
-- Clientes (tenants) y su registro de sucursales

CREATE TABLE control.tenants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    clave text NOT NULL UNIQUE CHECK (clave ~ '^[A-Z0-9-]{2,40}$'),
    nombre text NOT NULL,
    estado text NOT NULL DEFAULT 'ACTIVO'
        CHECK (estado IN ('ACTIVO', 'SUSPENDIDO', 'SOLO_LECTURA', 'BAJA')),
    data_plane_url text NOT NULL,
    creado_en timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE control.sucursales (
    tenant_id uuid NOT NULL REFERENCES control.tenants(id),
    clave text NOT NULL,
    data_plane_id uuid NOT NULL,              -- id de la sucursal en la base del cliente
    nombre text NOT NULL,
    activa boolean NOT NULL DEFAULT true,
    PRIMARY KEY (tenant_id, clave)
);

-- --------------------------------------------------------------------------
-- Identidades y asignaciones (ciclo-vida §1–§3)

CREATE TABLE control.identidades (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    idp_subject text UNIQUE,
    correo text NOT NULL,
    nombre text NOT NULL,
    estado text NOT NULL DEFAULT 'INVITADA'
        CHECK (estado IN ('INVITADA', 'REGISTRO_PENDIENTE', 'ACTIVA',
                          'BLOQUEADA_SEGURIDAD', 'SUSPENDIDA', 'BAJA_DEFINITIVA')),
    motivo_estado text,
    creado_en timestamptz NOT NULL DEFAULT now(),
    actualizado_en timestamptz NOT NULL DEFAULT now(),
    ultimo_acceso_en timestamptz
);

CREATE UNIQUE INDEX identidades_correo_unico ON control.identidades (lower(correo));

-- Una asignación = membresía en un cliente + rol + alcance. Su estado es el de
-- la membresía: una persona puede perder un cliente y conservar los demás.
CREATE TABLE control.asignaciones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    identidad_id uuid NOT NULL REFERENCES control.identidades(id),
    rol text NOT NULL REFERENCES control.roles(codigo),
    tenant_id uuid REFERENCES control.tenants(id),        -- NULL = todos (sólo roles globales)
    modulos text[],                                       -- NULL = los que permite el rol
    sucursales text[],                                    -- NULL = todas las del cliente
    condicionados text[] NOT NULL DEFAULT '{}',           -- p. ej. EXPORTAR_CSV
    estado text NOT NULL DEFAULT 'ACTIVA'
        CHECK (estado IN ('PENDIENTE', 'ACTIVA', 'SUSPENDIDA', 'EXPIRADA', 'REVOCADA')),
    vigente_desde timestamptz NOT NULL DEFAULT now(),
    vigente_hasta timestamptz,
    motivo text NOT NULL,
    creado_por uuid REFERENCES control.identidades(id),
    creado_en timestamptz NOT NULL DEFAULT now(),
    revocado_en timestamptz,
    CHECK (vigente_hasta IS NULL OR vigente_hasta > vigente_desde)
);

CREATE INDEX asignaciones_identidad ON control.asignaciones (identidad_id) WHERE estado = 'ACTIVA';

CREATE FUNCTION control.validar_asignacion() RETURNS trigger
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
    IF NEW.sucursales IS NOT NULL AND EXISTS (
        SELECT 1 FROM unnest(NEW.sucursales) s
        WHERE NOT EXISTS (SELECT 1 FROM control.sucursales cs WHERE cs.tenant_id = NEW.tenant_id AND cs.clave = s)
    ) THEN
        RAISE EXCEPTION 'Sucursal fuera del cliente de la asignación';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER asignaciones_validar BEFORE INSERT OR UPDATE ON control.asignaciones
    FOR EACH ROW EXECUTE FUNCTION control.validar_asignacion();

-- --------------------------------------------------------------------------
-- Sesiones (ciclo-vida §7). El navegador sólo guarda un token aleatorio; aquí
-- se guarda su huella, nunca el token.

CREATE TABLE control.sesiones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash bytea NOT NULL UNIQUE,
    identidad_id uuid NOT NULL REFERENCES control.identidades(id),
    asignacion_id uuid REFERENCES control.asignaciones(id),   -- NULL hasta elegir cliente y rol
    rol_activo text REFERENCES control.roles(codigo),
    tenant_id uuid REFERENCES control.tenants(id),
    creada_en timestamptz NOT NULL DEFAULT now(),
    ultimo_uso timestamptz NOT NULL DEFAULT now(),
    inactividad_max interval NOT NULL,
    expira_absoluta timestamptz NOT NULL,
    autenticado_en timestamptz NOT NULL,      -- auth_time del proveedor de identidad
    metodo_auth text NOT NULL,                -- LLAVE_FISICA | PASSKEY
    llave_fisica boolean NOT NULL,
    idp_sid text,
    ip inet,
    agente text,
    revocada_en timestamptz,
    motivo_revocacion text
);

CREATE INDEX sesiones_vigentes ON control.sesiones (identidad_id) WHERE revocada_en IS NULL;

-- Inicio de sesión en curso (state/nonce/PKCE). Caduca en 10 minutos y es de un solo uso.
CREATE TABLE control.solicitudes_acceso (
    state text PRIMARY KEY,
    verifier text NOT NULL,
    nonce text NOT NULL,
    destino text NOT NULL DEFAULT '/',
    proposito text NOT NULL CHECK (proposito IN ('ENTRAR', 'REAUTENTICAR')),
    sesion_id uuid REFERENCES control.sesiones(id),
    asignacion_destino uuid REFERENCES control.asignaciones(id),
    creada_en timestamptz NOT NULL DEFAULT now(),
    usada_en timestamptz
);

-- --------------------------------------------------------------------------
-- Auditoría inmutable (D-014, auditoria-alertas §2 y §6)

CREATE TABLE control.auditoria (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ocurrido_en timestamptz NOT NULL DEFAULT clock_timestamp(),
    tipo text NOT NULL,
    resultado text NOT NULL CHECK (resultado IN ('EXITO', 'RECHAZO', 'ERROR')),
    actor_id uuid,
    actor_tipo text NOT NULL CHECK (actor_tipo IN ('PERSONA', 'INTEGRACION', 'SISTEMA', 'ANONIMO')),
    rol text,
    tenant_id uuid,
    modulo text,
    sucursal text,
    accion text,
    recurso_tipo text,
    recurso_id text,
    sesion_id uuid,
    metodo_auth text,
    ip inet,
    motivo text,
    peticion_id text,
    sensibilidad text,
    politica text,
    detalle jsonb NOT NULL DEFAULT '{}',
    hash_anterior bytea,
    hash bytea NOT NULL
);

CREATE INDEX auditoria_actor ON control.auditoria (actor_id, ocurrido_en);
CREATE INDEX auditoria_tenant ON control.auditoria (tenant_id, ocurrido_en);

-- Cada evento encadena la huella del anterior: borrar o alterar uno rompe la cadena.
CREATE FUNCTION control.encadenar_auditoria() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    previo bytea;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('control.auditoria'));
    SELECT hash INTO previo FROM control.auditoria ORDER BY id DESC LIMIT 1;
    NEW.hash_anterior := previo;
    NEW.hash := digest(
        coalesce(previo, ''::bytea)
        || convert_to((to_jsonb(NEW) - 'hash' - 'hash_anterior')::text, 'UTF8'),
        'sha256'
    );
    RETURN NEW;
END $$;

CREATE FUNCTION control.auditoria_inmutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'La auditoría es de sólo anexado: % no permitido', TG_OP;
END $$;

CREATE TRIGGER auditoria_encadenar BEFORE INSERT ON control.auditoria
    FOR EACH ROW EXECUTE FUNCTION control.encadenar_auditoria();
CREATE TRIGGER auditoria_sin_cambios BEFORE UPDATE OR DELETE ON control.auditoria
    FOR EACH ROW EXECUTE FUNCTION control.auditoria_inmutable();
CREATE TRIGGER auditoria_sin_truncar BEFORE TRUNCATE ON control.auditoria
    FOR EACH STATEMENT EXECUTE FUNCTION control.auditoria_inmutable();

-- Devuelve el primer evento cuya huella no coincide (vacío = cadena íntegra).
CREATE FUNCTION control.verificar_auditoria()
RETURNS TABLE (id bigint, problema text)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    fila record;
    previo bytea := NULL;
    esperado bytea;
BEGIN
    FOR fila IN SELECT a.* FROM control.auditoria a ORDER BY a.id LOOP
        IF fila.hash_anterior IS DISTINCT FROM previo THEN
            id := fila.id; problema := 'eslabón anterior no coincide'; RETURN NEXT; RETURN;
        END IF;
        esperado := digest(
            coalesce(previo, ''::bytea)
            || convert_to((to_jsonb(fila) - 'hash' - 'hash_anterior')::text, 'UTF8'),
            'sha256'
        );
        IF esperado <> fila.hash THEN
            id := fila.id; problema := 'huella alterada'; RETURN NEXT; RETURN;
        END IF;
        previo := fila.hash;
    END LOOP;
END $$;

-- --------------------------------------------------------------------------
-- Permisos de la cuenta de la aplicación (control_app, creada por 000_roles.sh)

GRANT USAGE ON SCHEMA control TO control_app;
GRANT SELECT ON control.roles, control.modulos TO control_app;
GRANT SELECT, INSERT, UPDATE ON control.tenants, control.sucursales, control.identidades,
    control.asignaciones, control.sesiones, control.solicitudes_acceso TO control_app;
GRANT DELETE ON control.solicitudes_acceso TO control_app;
GRANT SELECT, INSERT ON control.auditoria TO control_app;
GRANT EXECUTE ON FUNCTION control.verificar_auditoria() TO control_app;
REVOKE ALL ON control.auditoria FROM PUBLIC;
REVOKE UPDATE, DELETE, TRUNCATE ON control.auditoria FROM control_app;
