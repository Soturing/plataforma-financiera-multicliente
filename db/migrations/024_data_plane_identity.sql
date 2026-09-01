BEGIN;

CREATE SCHEMA IF NOT EXISTS security_context;

CREATE TABLE security_context.tenant_identity (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    tenant_id uuid NOT NULL UNIQUE,
    provisioned_at timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION security_context.reject_tenant_identity_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'The data plane tenant identity is immutable';
END;
$$;

CREATE TRIGGER tenant_identity_immutable
BEFORE UPDATE OR DELETE ON security_context.tenant_identity
FOR EACH ROW EXECUTE FUNCTION security_context.reject_tenant_identity_mutation();

CREATE FUNCTION security_context.activate_request(
    p_tenant_id uuid,
    p_actor_id uuid,
    p_session_id uuid,
    p_branch_id uuid DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, security_context
AS $$
DECLARE
    v_expected_tenant_id uuid;
BEGIN
    IF p_tenant_id IS NULL OR p_actor_id IS NULL OR p_session_id IS NULL THEN
        RAISE EXCEPTION 'A complete authenticated request context is required'
            USING ERRCODE = '28000';
    END IF;

    IF current_setting('app.request_context_initialized', true) = 'true' THEN
        RAISE EXCEPTION 'The request context is immutable inside a transaction'
            USING ERRCODE = '28000';
    END IF;

    SELECT tenant_id
      INTO v_expected_tenant_id
      FROM security_context.tenant_identity
     WHERE singleton;

    IF v_expected_tenant_id IS NULL THEN
        RAISE EXCEPTION 'The data plane has not been provisioned'
            USING ERRCODE = '55000';
    END IF;
    IF v_expected_tenant_id <> p_tenant_id THEN
        RAISE EXCEPTION 'The authorized tenant does not match this data plane'
            USING ERRCODE = '28000';
    END IF;

    PERFORM set_config('app.tenant_id', p_tenant_id::text, true);
    PERFORM set_config('app.actor_id', p_actor_id::text, true);
    PERFORM set_config('app.session_id', p_session_id::text, true);
    PERFORM set_config('app.branch_id', COALESCE(p_branch_id::text, ''), true);
    PERFORM set_config('app.request_context_initialized', 'true', true);
END;
$$;

CREATE FUNCTION security_context.current_tenant_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid
$$;

CREATE FUNCTION security_context.current_actor_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.actor_id', true), '')::uuid
$$;

CREATE FUNCTION security_context.current_session_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.session_id', true), '')::uuid
$$;

CREATE FUNCTION security_context.current_branch_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.branch_id', true), '')::uuid
$$;

REVOKE ALL ON SCHEMA security_context FROM PUBLIC;
REVOKE ALL ON TABLE security_context.tenant_identity FROM PUBLIC;
REVOKE ALL ON FUNCTION security_context.reject_tenant_identity_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION security_context.activate_request(uuid, uuid, uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION security_context.current_tenant_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION security_context.current_actor_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION security_context.current_session_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION security_context.current_branch_id() FROM PUBLIC;

COMMENT ON TABLE security_context.tenant_identity IS
    'Immutable provisioning identity for this isolated tenant data plane.';
COMMENT ON FUNCTION security_context.activate_request IS
    'Rejects cross-tenant connections and establishes transaction-local request identity.';

COMMIT;
