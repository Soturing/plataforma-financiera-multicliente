BEGIN;

ALTER TABLE control.invitations
    ADD COLUMN proposed_valid_until timestamptz,
    ADD COLUMN proposed_all_modules boolean NOT NULL DEFAULT false,
    ADD COLUMN proposed_all_branches boolean NOT NULL DEFAULT false,
    ADD COLUMN reason text,
    ADD COLUMN accepted_identity_id uuid REFERENCES control.identities(id) ON DELETE RESTRICT,
    ADD COLUMN revoked_at timestamptz,
    ADD COLUMN revocation_reason text,
    ADD CONSTRAINT invitations_role_check CHECK (proposed_role_code IN (
        'CONSULTORA_DIRECTOR', 'CONSULTORA_SEGURIDAD', 'CONSULTORA_CAPTURISTA',
        'CLIENTE_RESPONSABLE', 'CLIENTE_FINANZAS', 'CLIENTE_OPERADOR',
        'SOPORTE_TECNICO'
    )),
    ADD CONSTRAINT invitations_reason_check CHECK (
        reason IS NULL OR length(btrim(reason)) BETWEEN 3 AND 500
    ),
    ADD CONSTRAINT invitations_assignment_expiration_check CHECK (
        proposed_valid_until IS NULL OR proposed_valid_until > created_at
    ),
    ADD CONSTRAINT invitations_revocation_check CHECK (
        (revoked_at IS NULL AND revocation_reason IS NULL)
        OR (
            revoked_at IS NOT NULL
            AND revoked_at >= created_at
            AND revocation_reason IS NOT NULL
            AND length(btrim(revocation_reason)) BETWEEN 3 AND 500
        )
    ),
    ADD CONSTRAINT invitations_acceptance_check CHECK (
        (consumed_at IS NULL) = (accepted_identity_id IS NULL)
    ),
    ADD CONSTRAINT invitations_terminal_state_check CHECK (
        num_nonnulls(consumed_at, revoked_at, replaced_by_id) <= 1
    );

CREATE TABLE control.invitation_modules (
    invitation_id uuid NOT NULL REFERENCES control.invitations(id) ON DELETE CASCADE,
    module_code text NOT NULL CHECK (module_code IN (
        'DOCUMENTOS', 'COMPROBANTES_INTERNOS', 'PROVEEDORES', 'CATALOGOS_CONTABLES',
        'VENTAS', 'FINANZAS', 'REPORTES', 'NOMINA', 'INVENTARIOS', 'RECETAS',
        'ADMIN_CLIENTES', 'IDENTIDADES_ACCESOS', 'AUDITORIA_SEGURIDAD',
        'INTEGRACIONES', 'OPERACION_TECNICA'
    )),
    PRIMARY KEY (invitation_id, module_code)
);

CREATE TABLE control.invitation_branches (
    invitation_id uuid NOT NULL REFERENCES control.invitations(id) ON DELETE CASCADE,
    branch_id uuid NOT NULL REFERENCES control.branches(id) ON DELETE RESTRICT,
    PRIMARY KEY (invitation_id, branch_id)
);

CREATE TABLE control.invitation_conditional_permissions (
    invitation_id uuid NOT NULL REFERENCES control.invitations(id) ON DELETE CASCADE,
    action_code text NOT NULL CHECK (length(btrim(action_code)) BETWEEN 3 AND 150),
    PRIMARY KEY (invitation_id, action_code)
);

CREATE TABLE control.installation_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    bootstrap_token_digest bytea UNIQUE,
    bootstrap_token_created_at timestamptz,
    bootstrap_token_expires_at timestamptz,
    completed_at timestamptz,
    completed_by_identity_id uuid REFERENCES control.identities(id) ON DELETE RESTRICT,
    CHECK (
        (bootstrap_token_digest IS NULL) =
        (bootstrap_token_created_at IS NULL AND bootstrap_token_expires_at IS NULL)
    ),
    CHECK (
        (completed_at IS NULL AND completed_by_identity_id IS NULL)
        OR (completed_at IS NOT NULL AND completed_by_identity_id IS NOT NULL)
    ),
    CHECK (
        bootstrap_token_expires_at IS NULL
        OR bootstrap_token_expires_at > bootstrap_token_created_at
    ),
    CHECK (completed_at IS NULL OR bootstrap_token_digest IS NULL)
);

CREATE FUNCTION security_audit.append_event(
    p_event_type text,
    p_result control.audit_result,
    p_actor_id uuid,
    p_actor_type control.actor_type,
    p_effective_role text,
    p_tenant_id uuid,
    p_module_code text,
    p_branch_id uuid,
    p_action_code text,
    p_resource_type text,
    p_resource_id text,
    p_session_id uuid,
    p_auth_level control.auth_level,
    p_reason_code text,
    p_request_id uuid,
    p_correlation_id uuid,
    p_affected_count bigint,
    p_affected_bytes bigint,
    p_sensitivity text,
    p_policy_code text,
    p_metadata jsonb DEFAULT '{}'::jsonb
)
RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE
    v_event_id uuid := gen_random_uuid();
    v_occurred_at timestamptz := clock_timestamp();
    v_previous_hash bytea;
    v_event_hash bytea;
BEGIN
    IF p_metadata IS NULL OR jsonb_typeof(p_metadata) <> 'object' THEN
        RAISE EXCEPTION 'Audit metadata must be a JSON object';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtext('security_audit.events.hash_chain'));
    SELECT event_hash
      INTO v_previous_hash
      FROM security_audit.events
     ORDER BY sequence_id DESC
     LIMIT 1;

    v_event_hash := digest(
        concat_ws('|',
            COALESCE(encode(v_previous_hash, 'hex'), ''),
            v_event_id::text,
            v_occurred_at::text,
            p_event_type,
            p_result::text,
            COALESCE(p_actor_id::text, ''),
            p_actor_type::text,
            COALESCE(p_effective_role, ''),
            COALESCE(p_tenant_id::text, ''),
            COALESCE(p_module_code, ''),
            COALESCE(p_branch_id::text, ''),
            p_action_code,
            COALESCE(p_resource_type, ''),
            COALESCE(p_resource_id, ''),
            COALESCE(p_session_id::text, ''),
            COALESCE(p_auth_level::text, ''),
            COALESCE(p_reason_code, ''),
            p_request_id::text,
            COALESCE(p_correlation_id::text, ''),
            COALESCE(p_affected_count::text, ''),
            COALESCE(p_affected_bytes::text, ''),
            p_sensitivity,
            p_policy_code,
            p_metadata::text
        ),
        'sha256'
    );

    INSERT INTO security_audit.events (
        event_id, occurred_at, event_type, result, actor_id, actor_type,
        effective_role, tenant_id, module_code, branch_id, action_code,
        resource_type, resource_id, session_id, auth_level, reason_code,
        request_id, correlation_id, affected_count, affected_bytes,
        sensitivity, policy_code, metadata, previous_hash, event_hash
    ) VALUES (
        v_event_id, v_occurred_at, p_event_type, p_result, p_actor_id, p_actor_type,
        p_effective_role, p_tenant_id, p_module_code, p_branch_id, p_action_code,
        p_resource_type, p_resource_id, p_session_id, p_auth_level, p_reason_code,
        p_request_id, p_correlation_id, p_affected_count, p_affected_bytes,
        p_sensitivity, p_policy_code, p_metadata, v_previous_hash, v_event_hash
    );

    RETURN v_event_id;
END;
$$;

COMMENT ON TABLE control.installation_state IS
    'Singleton that makes the first-director installation credential single-use.';
COMMENT ON FUNCTION security_audit.append_event IS
    'Serializes audit writes and links each event hash to the previous event.';

COMMIT;
