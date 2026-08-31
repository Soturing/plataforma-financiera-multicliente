BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS control;
CREATE SCHEMA IF NOT EXISTS security_audit;

CREATE TYPE control.tenant_state AS ENUM (
    'APROVISIONANDO', 'ACTIVO', 'SUSPENDIDO', 'SOLO_LECTURA', 'RETENCION', 'BAJA_PROGRAMADA', 'CERRADO'
);
CREATE TYPE control.identity_state AS ENUM (
    'INVITADA', 'REGISTRO_PENDIENTE', 'ACTIVA', 'BLOQUEADA_SEGURIDAD', 'SUSPENDIDA', 'BAJA_DEFINITIVA'
);
CREATE TYPE control.actor_type AS ENUM ('PERSONA', 'INTEGRACION', 'SISTEMA');
CREATE TYPE control.assignment_state AS ENUM ('PENDIENTE', 'ACTIVA', 'SUSPENDIDA', 'EXPIRADA', 'REVOCADA');
CREATE TYPE control.authenticator_state AS ENUM ('ACTIVO', 'PERDIDO', 'REVOCADO');
CREATE TYPE control.session_state AS ENUM ('ACTIVA', 'REVOCADA', 'EXPIRADA');
CREATE TYPE control.auth_level AS ENUM ('FEDERADA', 'PASSKEY', 'LLAVE_FISICA', 'RECUPERACION');
CREATE TYPE control.audit_result AS ENUM ('EXITO', 'RECHAZO', 'ERROR');

CREATE TABLE control.tenants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
    display_name text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 2 AND 200),
    state control.tenant_state NOT NULL DEFAULT 'APROVISIONANDO',
    data_plane_reference text,
    service_valid_until timestamptz,
    retention_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (retention_until IS NULL OR state IN ('RETENCION', 'BAJA_PROGRAMADA', 'CERRADO'))
);

CREATE TABLE control.identities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_type control.actor_type NOT NULL DEFAULT 'PERSONA',
    identity_provider text NOT NULL CHECK (length(btrim(identity_provider)) BETWEEN 2 AND 100),
    provider_subject text NOT NULL CHECK (length(btrim(provider_subject)) BETWEEN 2 AND 500),
    email text,
    display_name text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 2 AND 200),
    state control.identity_state NOT NULL DEFAULT 'INVITADA',
    security_stamp uuid NOT NULL DEFAULT gen_random_uuid(),
    last_activity_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (identity_provider, provider_subject),
    CHECK (email IS NULL OR email = lower(email))
);

CREATE UNIQUE INDEX identities_email_person_unique
    ON control.identities (lower(email))
    WHERE email IS NOT NULL AND actor_type = 'PERSONA';

CREATE TABLE control.branches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES control.tenants(id) ON DELETE RESTRICT,
    data_plane_branch_id uuid NOT NULL,
    code text NOT NULL CHECK (length(btrim(code)) BETWEEN 1 AND 50),
    display_name text NOT NULL CHECK (length(btrim(display_name)) BETWEEN 1 AND 200),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, data_plane_branch_id),
    UNIQUE (tenant_id, code)
);

CREATE TABLE control.invitations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text NOT NULL CHECK (email = lower(email)),
    tenant_id uuid REFERENCES control.tenants(id) ON DELETE RESTRICT,
    token_digest bytea NOT NULL UNIQUE,
    proposed_role_code text NOT NULL,
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    replaced_by_id uuid REFERENCES control.invitations(id) ON DELETE RESTRICT,
    invited_by_identity_id uuid NOT NULL REFERENCES control.identities(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (expires_at > created_at),
    CHECK (consumed_at IS NULL OR consumed_at >= created_at)
);

CREATE TABLE control.authenticators (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    identity_id uuid NOT NULL REFERENCES control.identities(id) ON DELETE RESTRICT,
    provider_authenticator_id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('PASSKEY', 'HARDWARE_KEY', 'RECOVERY_CODE_SET')),
    label text NOT NULL CHECK (length(btrim(label)) BETWEEN 1 AND 100),
    state control.authenticator_state NOT NULL DEFAULT 'ACTIVO',
    registered_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    revoked_at timestamptz,
    UNIQUE (identity_id, provider_authenticator_id),
    CHECK ((state = 'REVOCADO') = (revoked_at IS NOT NULL))
);

CREATE TABLE control.access_assignments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    identity_id uuid NOT NULL REFERENCES control.identities(id) ON DELETE RESTRICT,
    tenant_id uuid REFERENCES control.tenants(id) ON DELETE RESTRICT,
    role_code text NOT NULL CHECK (role_code IN (
        'CONSULTORA_DIRECTOR', 'CONSULTORA_SEGURIDAD', 'CONSULTORA_CAPTURISTA',
        'CLIENTE_RESPONSABLE', 'CLIENTE_FINANZAS', 'CLIENTE_OPERADOR',
        'SOPORTE_TECNICO', 'INTEGRACION_API'
    )),
    state control.assignment_state NOT NULL DEFAULT 'PENDIENTE',
    all_modules boolean NOT NULL DEFAULT false,
    all_branches boolean NOT NULL DEFAULT false,
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_until timestamptz,
    reason text,
    created_by_identity_id uuid NOT NULL REFERENCES control.identities(id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (valid_until IS NULL OR valid_until > valid_from),
    CHECK (
        (role_code IN ('CONSULTORA_DIRECTOR', 'CONSULTORA_SEGURIDAD') AND tenant_id IS NULL)
        OR (role_code = 'SOPORTE_TECNICO')
        OR (role_code IN (
            'CONSULTORA_CAPTURISTA', 'CLIENTE_RESPONSABLE', 'CLIENTE_FINANZAS',
            'CLIENTE_OPERADOR', 'INTEGRACION_API'
        ) AND tenant_id IS NOT NULL)
    )
);

CREATE INDEX access_assignments_identity_state_idx
    ON control.access_assignments (identity_id, state, valid_until);
CREATE INDEX access_assignments_tenant_state_idx
    ON control.access_assignments (tenant_id, state);

CREATE TABLE control.assignment_modules (
    assignment_id uuid NOT NULL REFERENCES control.access_assignments(id) ON DELETE CASCADE,
    module_code text NOT NULL CHECK (module_code IN (
        'DOCUMENTOS', 'COMPROBANTES_INTERNOS', 'PROVEEDORES', 'CATALOGOS_CONTABLES',
        'VENTAS', 'FINANZAS', 'REPORTES', 'NOMINA', 'INVENTARIOS', 'RECETAS',
        'ADMIN_CLIENTES', 'IDENTIDADES_ACCESOS', 'AUDITORIA_SEGURIDAD',
        'INTEGRACIONES', 'OPERACION_TECNICA'
    )),
    PRIMARY KEY (assignment_id, module_code)
);

CREATE TABLE control.assignment_branches (
    assignment_id uuid NOT NULL REFERENCES control.access_assignments(id) ON DELETE CASCADE,
    branch_id uuid NOT NULL REFERENCES control.branches(id) ON DELETE RESTRICT,
    PRIMARY KEY (assignment_id, branch_id)
);

CREATE TABLE control.conditional_permissions (
    assignment_id uuid NOT NULL REFERENCES control.access_assignments(id) ON DELETE CASCADE,
    action_code text NOT NULL CHECK (length(btrim(action_code)) BETWEEN 3 AND 150),
    granted_by_identity_id uuid NOT NULL REFERENCES control.identities(id) ON DELETE RESTRICT,
    reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 3 AND 500),
    valid_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (assignment_id, action_code)
);

CREATE TABLE control.sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    identity_id uuid NOT NULL REFERENCES control.identities(id) ON DELETE RESTRICT,
    provider_session_digest bytea NOT NULL UNIQUE,
    security_stamp uuid NOT NULL,
    state control.session_state NOT NULL DEFAULT 'ACTIVA',
    auth_level control.auth_level NOT NULL,
    authenticated_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    idle_expires_at timestamptz NOT NULL,
    absolute_expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    revocation_reason text,
    CHECK (idle_expires_at <= absolute_expires_at),
    CHECK ((state = 'REVOCADA') = (revoked_at IS NOT NULL))
);

CREATE INDEX sessions_identity_state_idx
    ON control.sessions (identity_id, state, absolute_expires_at);

CREATE TABLE security_audit.events (
    sequence_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    event_type text NOT NULL,
    result control.audit_result NOT NULL,
    actor_id uuid REFERENCES control.identities(id) ON DELETE RESTRICT,
    actor_type control.actor_type NOT NULL,
    effective_role text,
    tenant_id uuid REFERENCES control.tenants(id) ON DELETE RESTRICT,
    module_code text,
    branch_id uuid REFERENCES control.branches(id) ON DELETE RESTRICT,
    action_code text NOT NULL,
    resource_type text,
    resource_id text,
    session_id uuid REFERENCES control.sessions(id) ON DELETE RESTRICT,
    auth_level control.auth_level,
    reason_code text,
    request_id uuid NOT NULL,
    correlation_id uuid,
    affected_count bigint,
    affected_bytes bigint,
    sensitivity text NOT NULL,
    policy_code text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    previous_hash bytea,
    event_hash bytea NOT NULL,
    CHECK (jsonb_typeof(metadata) = 'object')
);

CREATE INDEX security_events_actor_time_idx
    ON security_audit.events (actor_id, occurred_at DESC);
CREATE INDEX security_events_tenant_time_idx
    ON security_audit.events (tenant_id, occurred_at DESC);
CREATE INDEX security_events_type_time_idx
    ON security_audit.events (event_type, occurred_at DESC);

CREATE FUNCTION security_audit.reject_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'security_audit.events is append-only';
END;
$$;

CREATE TRIGGER security_events_append_only
BEFORE UPDATE OR DELETE ON security_audit.events
FOR EACH ROW EXECUTE FUNCTION security_audit.reject_event_mutation();

COMMENT ON TABLE control.tenants IS
    'Shared control-plane metadata only. Financial or document content is forbidden here.';
COMMENT ON COLUMN control.invitations.token_digest IS
    'One-way digest only; invitation tokens are never stored in plaintext.';
COMMENT ON COLUMN control.sessions.provider_session_digest IS
    'One-way digest of the external provider session identifier; never a bearer token.';
COMMENT ON TABLE security_audit.events IS
    'Append-only security metadata. Financial payloads, tokens and document contents are forbidden.';

COMMIT;
