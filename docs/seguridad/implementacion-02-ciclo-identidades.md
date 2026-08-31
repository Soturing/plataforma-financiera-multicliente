# Implementación 02 — Ciclo inicial de identidades

Estado: **implementado en rama; pendiente de activar con un proveedor de identidad**.
Fecha: 2026-08-31.

## Objetivo

Construir las operaciones administrativas necesarias para iniciar el sistema sin contraseñas locales, invitar usuarios y cortar accesos de forma inmediata.

## Primer director

El primer director se crea exclusivamente mediante un procedimiento de consola, no mediante un endpoint público.

1. un operador con acceso de instalación genera una credencial aleatoria;
2. la base conserva únicamente su resumen SHA-256;
3. la credencial caduca después de 30 minutos;
4. el director debe existir previamente en el proveedor OIDC;
5. se registran dos referencias distintas de llaves físicas;
6. se crea una asignación global nominativa;
7. la credencial se invalida dentro de la misma transacción; y
8. el evento queda en auditoría encadenada.

Una credencial vencida puede reemplazarse. Una credencial consumida no puede reutilizarse y el procedimiento no permite crear un segundo “primer director”.

## Invitaciones

Las invitaciones administrativas incluyen:

- correo normalizado;
- rol propuesto;
- tenant, cuando corresponde;
- módulos y sucursales;
- permisos condicionados válidos para el rol;
- vigencia de la futura asignación;
- motivo;
- expiración fija de 24 horas; y
- token aleatorio mostrado una sola vez y almacenado únicamente como resumen.

Crear una nueva invitación reemplaza cualquier invitación pendiente anterior para el mismo correo y tenant. Las solicitudes concurrentes para el mismo destino se serializan en PostgreSQL para no dejar dos tokens utilizables. Los metadatos de auditoría no incluyen el correo ni el token.

## Suspensión y sesiones

Suspender una identidad ejecuta atómicamente:

- estado `SUSPENDIDA`;
- rotación del `security_stamp`;
- revocación de todas sus sesiones activas;
- suspensión de sus asignaciones activas o pendientes;
- revocación de invitaciones pendientes; y
- evento de auditoría con cantidades afectadas.

No se permite la autosuspensión. Suspender una identidad privilegiada es una acción C3 y exige autenticación reciente con llave física.

Cada usuario puede revocar sus propias sesiones. Director y administrador de seguridad pueden revocar sesiones ajenas mediante una acción C2.

## Auditoría encadenada

La función `security_audit.append_event` serializa las escrituras y calcula cada hash utilizando el hash del evento anterior. La tabla continúa rechazando `UPDATE` y `DELETE`.

La separación definitiva de credenciales de escritura, la firma diaria externa y la copia inmutable siguen pendientes de infraestructura.

## API preparada

- `POST /api/v1/security/invitations`
- `POST /api/v1/security/identities/{identity_id}/suspend`
- `POST /api/v1/security/sessions/{session_id}/revoke`

Estas rutas fallan cerradas sin OIDC y plano de control configurados. La instancia local que continúa sirviendo la demo no fue reiniciada durante esta construcción.

## Verificación

- migraciones recreadas desde cero en bases PostgreSQL aisladas;
- 133 pruebas automatizadas aprobadas;
- compilación de módulos Python sin errores;
- revisión de espacios y conflictos del diff sin errores; y
- servicio local existente verificado en estado saludable sin reiniciarlo.

## Pendientes antes de activar

1. elegir el proveedor OIDC/WebAuthn;
2. registrar al primer director y sus dos llaves reales;
3. implementar aceptación de invitación después de autenticar el correo en el proveedor;
4. entregar invitaciones mediante un canal transaccional;
5. implementar recuperación asistida y reactivación;
6. registrar también los intentos de autorización rechazados mediante el canal independiente de auditoría; y
7. conectar los endpoints financieros a este contexto.
