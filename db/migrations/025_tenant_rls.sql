BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenant_runtime') THEN
        CREATE ROLE tenant_runtime
            NOLOGIN NOSUPERUSER INHERIT NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenant_reports') THEN
        CREATE ROLE tenant_reports
            NOLOGIN NOSUPERUSER INHERIT NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
END;
$$;

CREATE FUNCTION security_context.provisioned_tenant_id()
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, security_context
AS $$
    SELECT tenant_id FROM security_context.tenant_identity WHERE singleton
$$;

CREATE OR REPLACE FUNCTION security_context.activate_request(
    p_tenant_id uuid,
    p_actor_id uuid,
    p_session_id uuid,
    p_branch_id uuid DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, security_context
AS $$
DECLARE
    v_expected_tenant_id uuid;
    v_unsafe_role boolean;
    v_owns_protected_tables boolean;
BEGIN
    IF p_tenant_id IS NULL OR p_actor_id IS NULL OR p_session_id IS NULL THEN
        RAISE EXCEPTION 'A complete authenticated request context is required'
            USING ERRCODE = '28000';
    END IF;

    SELECT rolsuper OR rolbypassrls OR rolcreaterole
      INTO v_unsafe_role
      FROM pg_roles
     WHERE rolname = current_user;
    SELECT EXISTS (
        SELECT 1
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname IN ('catalog', 'core', 'ocr', 'ai', 'audit', 'finance')
           AND c.relkind IN ('r', 'p')
           AND pg_has_role(current_user, c.relowner, 'MEMBER')
    ) INTO v_owns_protected_tables;
    IF COALESCE(v_unsafe_role, true)
       OR v_owns_protected_tables
       OR NOT (
           pg_has_role(current_user, 'tenant_runtime', 'MEMBER')
           OR pg_has_role(current_user, 'tenant_reports', 'MEMBER')
       ) THEN
        RAISE EXCEPTION 'The connection principal is not a restricted tenant role'
            USING ERRCODE = '42501';
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

DO $$
DECLARE
    item record;
BEGIN
    FOR item IN
        SELECT n.nspname AS schema_name, c.relname AS table_name
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname IN ('catalog', 'core', 'ocr', 'ai', 'audit', 'finance')
           AND c.relkind IN ('r', 'p')
         ORDER BY n.nspname, c.relname
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.%I ADD COLUMN tenant_id uuid',
            item.schema_name,
            item.table_name
        );
        EXECUTE format(
            'ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',
            item.schema_name,
            item.table_name
        );
        EXECUTE format(
            'ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY',
            item.schema_name,
            item.table_name
        );
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I.%I '
            'USING (tenant_id = security_context.current_tenant_id() '
            'AND tenant_id = security_context.provisioned_tenant_id()) '
            'WITH CHECK (tenant_id = security_context.current_tenant_id() '
            'AND tenant_id = security_context.provisioned_tenant_id())',
            item.schema_name,
            item.table_name
        );
    END LOOP;
END;
$$;

DO $$
DECLARE
    item record;
BEGIN
    FOR item IN
        SELECT schemaname AS schema_name, viewname AS view_name
          FROM pg_views
         WHERE schemaname IN ('analytics', 'finance')
    LOOP
        EXECUTE format(
            'ALTER VIEW %I.%I SET (security_invoker = true)',
            item.schema_name,
            item.view_name
        );
    END LOOP;
END;
$$;

CREATE FUNCTION security_context.finalize_tenant_isolation()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, security_context
AS $$
DECLARE
    item record;
    v_expected_tenant_id uuid;
    v_conflicting_rows bigint;
BEGIN
    SELECT tenant_id
      INTO v_expected_tenant_id
      FROM security_context.tenant_identity
     WHERE singleton;
    IF v_expected_tenant_id IS NULL THEN
        RAISE EXCEPTION 'The data plane must be bound before isolation is finalized';
    END IF;

    FOR item IN
        SELECT n.nspname AS schema_name, c.relname AS table_name
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname IN ('catalog', 'core', 'ocr', 'ai', 'audit', 'finance')
           AND c.relkind IN ('r', 'p')
         ORDER BY n.nspname, c.relname
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.%I DISABLE ROW LEVEL SECURITY',
            item.schema_name,
            item.table_name
        );
        EXECUTE format(
            'SELECT count(*) FROM %I.%I WHERE tenant_id IS NOT NULL AND tenant_id <> $1',
            item.schema_name,
            item.table_name
        ) INTO v_conflicting_rows USING v_expected_tenant_id;
        IF v_conflicting_rows > 0 THEN
            RAISE EXCEPTION 'Conflicting tenant rows found in %.%',
                item.schema_name, item.table_name;
        END IF;
        EXECUTE format(
            'UPDATE %I.%I SET tenant_id = $1 WHERE tenant_id IS NULL',
            item.schema_name,
            item.table_name
        ) USING v_expected_tenant_id;
        EXECUTE format(
            'ALTER TABLE %I.%I ALTER COLUMN tenant_id '
            'SET DEFAULT security_context.current_tenant_id()',
            item.schema_name,
            item.table_name
        );
        EXECUTE format(
            'ALTER TABLE %I.%I ALTER COLUMN tenant_id SET NOT NULL',
            item.schema_name,
            item.table_name
        );
        EXECUTE format(
            'ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',
            item.schema_name,
            item.table_name
        );
        EXECUTE format(
            'ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY',
            item.schema_name,
            item.table_name
        );
    END LOOP;

    FOR item IN
        SELECT schemaname AS schema_name, viewname AS view_name
          FROM pg_views
         WHERE schemaname IN ('analytics', 'finance')
    LOOP
        EXECUTE format(
            'ALTER VIEW %I.%I SET (security_invoker = true)',
            item.schema_name,
            item.view_name
        );
    END LOOP;
END;
$$;

REVOKE ALL ON FUNCTION security_context.provisioned_tenant_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION security_context.finalize_tenant_isolation() FROM PUBLIC;
GRANT USAGE ON SCHEMA security_context TO tenant_runtime, tenant_reports;
GRANT SELECT ON security_context.tenant_identity TO tenant_runtime, tenant_reports;
GRANT EXECUTE ON FUNCTION security_context.activate_request(uuid, uuid, uuid, uuid)
    TO tenant_runtime, tenant_reports;
GRANT EXECUTE ON FUNCTION security_context.current_tenant_id()
    TO tenant_runtime, tenant_reports;
GRANT EXECUTE ON FUNCTION security_context.current_actor_id()
    TO tenant_runtime, tenant_reports;
GRANT EXECUTE ON FUNCTION security_context.current_session_id()
    TO tenant_runtime, tenant_reports;
GRANT EXECUTE ON FUNCTION security_context.current_branch_id()
    TO tenant_runtime, tenant_reports;
GRANT EXECUTE ON FUNCTION security_context.provisioned_tenant_id()
    TO tenant_runtime, tenant_reports;

GRANT USAGE ON SCHEMA catalog, core, ocr, ai, audit, finance, analytics
    TO tenant_runtime, tenant_reports;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA
    catalog, core, ocr, ai, finance TO tenant_runtime;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA audit TO tenant_runtime;
GRANT UPDATE (sucursal_confirmada_id, confirmada_por, confirmada_en)
    ON audit.inferencias_sucursal TO tenant_runtime;
GRANT SELECT ON ALL TABLES IN SCHEMA
    catalog, core, ocr, ai, audit, finance, analytics TO tenant_reports;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO tenant_runtime;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA
    catalog, core, ocr, ai, audit, finance TO tenant_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA
    catalog, core, ocr, ai, audit, finance TO tenant_reports;

COMMENT ON FUNCTION security_context.finalize_tenant_isolation IS
    'Backfills one immutable tenant id and completes FORCE RLS during one-time provisioning.';

COMMIT;
