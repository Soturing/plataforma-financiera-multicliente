-- Fase 6: ciclo de vida (ciclo-vida-usuarios §8–§15).

-- Registrar un autenticador desde una sesión existente (acción iniciada por la app).
ALTER TABLE control.solicitudes_acceso DROP CONSTRAINT solicitudes_acceso_proposito_check;
ALTER TABLE control.solicitudes_acceso ADD CONSTRAINT solicitudes_acceso_proposito_check
    CHECK (proposito IN ('ENTRAR', 'REAUTENTICAR', 'REGISTRAR_AUTENTICADOR'));

-- Tras entrar con un código de recuperación, la persona debe registrar un autenticador nuevo.
ALTER TABLE control.identidades ADD COLUMN requiere_nuevo_autenticador boolean NOT NULL DEFAULT false;
-- Último aviso de inactividad enviado (para no repetirlo en el mismo ciclo).
ALTER TABLE control.identidades ADD COLUMN aviso_inactividad_en timestamptz;

-- Recuperación asistida con espera inicial de 24 horas (§10.1).
CREATE TABLE control.recuperaciones (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    identidad_id uuid NOT NULL REFERENCES control.identidades(id),
    solicitada_por uuid NOT NULL REFERENCES control.identidades(id),
    motivo text NOT NULL,
    verificacion text NOT NULL,            -- cómo se verificó la identidad por un canal previo
    solicitada_en timestamptz NOT NULL DEFAULT now(),
    ejecutable_desde timestamptz NOT NULL,
    estado text NOT NULL DEFAULT 'PENDIENTE' CHECK (estado IN ('PENDIENTE', 'EJECUTADA', 'CANCELADA')),
    resuelta_en timestamptz,
    resuelta_por uuid REFERENCES control.identidades(id),
    CHECK (solicitada_por <> identidad_id),
    CHECK (ejecutable_desde >= solicitada_en + interval '24 hours')
);

CREATE UNIQUE INDEX recuperacion_pendiente_unica ON control.recuperaciones (identidad_id) WHERE estado = 'PENDIENTE';

-- Registro de notificaciones enviadas: sólo metadatos, nunca el contenido.
CREATE TABLE control.notificaciones (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    identidad_id uuid REFERENCES control.identidades(id),
    destinatario text NOT NULL,
    tipo text NOT NULL,
    creada_en timestamptz NOT NULL DEFAULT now(),
    estado text NOT NULL CHECK (estado IN ('ENVIADA', 'ERROR')),
    error text
);

GRANT SELECT, INSERT, UPDATE ON control.recuperaciones TO control_app;
GRANT SELECT, INSERT ON control.notificaciones TO control_app;
