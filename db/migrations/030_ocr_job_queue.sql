-- Cola de trabajos OCR sobre PostgreSQL.
-- Reemplaza el proceso por factura: workers permanentes toman trabajos con
-- FOR UPDATE SKIP LOCKED, renuevan una reserva (lease) mientras leen y
-- reintentan con espera creciente. Si un worker muere, la reserva vence y el
-- trabajo vuelve a la cola.
BEGIN;

CREATE TYPE core.estado_trabajo_ocr AS ENUM (
    'en_cola', 'procesando', 'completado', 'fallido', 'cancelado'
);

CREATE TABLE core.trabajos_ocr (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    factura_id uuid NOT NULL REFERENCES core.facturas(id) ON DELETE CASCADE,
    estado core.estado_trabajo_ocr NOT NULL DEFAULT 'en_cola',
    -- 1 = interactivo (una factura subida a mano), 3 = carga masiva, 5 = lote PDF.
    prioridad smallint NOT NULL DEFAULT 5 CHECK (prioridad BETWEEN 1 AND 9),
    intentos smallint NOT NULL DEFAULT 0 CHECK (intentos >= 0),
    max_intentos smallint NOT NULL DEFAULT 3 CHECK (max_intentos >= 1),
    disponible_en timestamptz NOT NULL DEFAULT now(),
    reservado_por text,
    reservado_hasta timestamptz,
    ultimo_error text,
    creado_en timestamptz NOT NULL DEFAULT now(),
    iniciado_en timestamptz,
    terminado_en timestamptz,
    CHECK ((estado = 'procesando') = (reservado_por IS NOT NULL))
);

-- Una factura solo puede tener un trabajo activo a la vez.
CREATE UNIQUE INDEX trabajos_ocr_activo_idx
    ON core.trabajos_ocr (factura_id) WHERE estado IN ('en_cola', 'procesando');
-- Orden de toma: prioridad, luego llegada.
CREATE INDEX trabajos_ocr_toma_idx
    ON core.trabajos_ocr (prioridad, creado_en, id) WHERE estado = 'en_cola';
CREATE INDEX trabajos_ocr_reserva_idx
    ON core.trabajos_ocr (reservado_hasta) WHERE estado = 'procesando';
CREATE INDEX trabajos_ocr_terminado_idx
    ON core.trabajos_ocr (terminado_en) WHERE terminado_en IS NOT NULL;

-- Registro de workers vivos para mostrar el estado de la cola y detectar
-- cuando nadie está leyendo.
CREATE TABLE core.workers_ocr (
    id text PRIMARY KEY,
    pid integer NOT NULL,
    host text NOT NULL,
    iniciado_en timestamptz NOT NULL DEFAULT now(),
    ultimo_latido timestamptz NOT NULL DEFAULT now(),
    procesados integer NOT NULL DEFAULT 0,
    trabajo_actual bigint
);

COMMIT;
