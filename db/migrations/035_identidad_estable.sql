-- 035: identidad estable junto a cada columna *_por (roadmap §3.8.2, revisión de BD punto 3).
--
-- Las columnas `*_por` guardan una etiqueta de texto (nombre o correo de quien operó). Las
-- identidades viven en el plano de control, que es otra base, así que no hay clave foránea posible;
-- en su lugar, cada `<col>_por` gana un `<col>_por_id uuid` con el identificador estable de la
-- identidad. La aplicación declara quién opera con `app.identidad` al abrir la conexión
-- (app/database.py) y este trigger copia ese valor cuando se escribe o cambia la etiqueta.
--
-- Sin sesión (workers, modo abierto) `app.identidad` está vacío y el `_id` queda NULL: el dato
-- no se inventa. Las filas anteriores no se rellenan; no hay de dónde sacar su identificador.

CREATE OR REPLACE FUNCTION seguridad.completar_identidad() RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
DECLARE
    texto text := current_setting('app.identidad', true);
    identidad uuid := CASE WHEN texto ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                           THEN texto::uuid END;
    nuevo jsonb := to_jsonb(NEW);
    viejo jsonb := CASE WHEN TG_OP = 'UPDATE' THEN to_jsonb(OLD) END;
    cambios jsonb := '{}'::jsonb;
    columna text;
BEGIN
    -- TG_ARGV trae los nombres de las columnas `*_por` de la tabla.
    FOREACH columna IN ARRAY TG_ARGV LOOP
        IF nuevo ->> columna IS NOT NULL
           AND (viejo IS NULL OR viejo ->> columna IS DISTINCT FROM nuevo ->> columna) THEN
            cambios := cambios || jsonb_build_object(columna || '_id', identidad);
        END IF;
    END LOOP;
    RETURN jsonb_populate_record(NEW, cambios);
END
$$;

DO $$
DECLARE
    tabla record;
    columna text;
BEGIN
    FOR tabla IN
        SELECT c.table_schema AS esquema, c.table_name AS nombre,
               array_agg(c.column_name::text ORDER BY c.column_name) AS columnas
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE t.table_type = 'BASE TABLE'
          AND c.table_schema IN ('audit', 'catalog', 'core', 'finance')
          AND c.column_name LIKE '%\_por'
          AND c.data_type = 'text'
          -- `reservado_por` es el identificador de un worker, no de una persona.
          AND NOT (c.table_schema = 'core' AND c.table_name = 'trabajos_ocr')
        GROUP BY c.table_schema, c.table_name
    LOOP
        FOREACH columna IN ARRAY tabla.columnas LOOP
            EXECUTE format('ALTER TABLE %I.%I ADD COLUMN IF NOT EXISTS %I uuid', tabla.esquema, tabla.nombre, columna || '_id');
        END LOOP;
        EXECUTE format('DROP TRIGGER IF EXISTS completar_identidad ON %I.%I', tabla.esquema, tabla.nombre);
        EXECUTE format(
            'CREATE TRIGGER completar_identidad BEFORE INSERT OR UPDATE ON %I.%I '
            'FOR EACH ROW EXECUTE FUNCTION seguridad.completar_identidad(%s)',
            tabla.esquema, tabla.nombre,
            (SELECT string_agg(quote_literal(x), ', ') FROM unnest(tabla.columnas) AS x)
        );
    END LOOP;
END
$$;
