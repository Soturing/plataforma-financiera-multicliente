#!/bin/sh
# Crea la cuenta de la aplicación del plano de control: sin propiedad de tablas,
# sin SUPERUSER ni BYPASSRLS (arquitectura-aislamiento §8).

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE control_app LOGIN PASSWORD '${CONTROL_APP_PASSWORD}'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
