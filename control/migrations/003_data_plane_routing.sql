BEGIN;

ALTER TABLE control.tenants
    ADD CONSTRAINT tenants_data_plane_reference_format CHECK (
        data_plane_reference IS NULL
        OR data_plane_reference ~ '^[a-z0-9][a-z0-9_-]{1,62}$'
    );

CREATE UNIQUE INDEX tenants_data_plane_reference_unique
    ON control.tenants (data_plane_reference)
    WHERE data_plane_reference IS NOT NULL;

COMMENT ON COLUMN control.tenants.data_plane_reference IS
    'Opaque secret-registry key only. Database credentials and financial locations are forbidden.';

COMMIT;
