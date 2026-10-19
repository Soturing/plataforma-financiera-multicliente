# Fase 6 — Ciclo de vida de las personas

Estado: implementado (2026-10-18). Referencia funcional: [ciclo-vida-usuarios.md](ciclo-vida-usuarios.md).

## 1. Qué hay en la aplicación

En **Usuarios y accesos** (`#/accesos`):

| Sección | Quién | Qué permite |
|---|---|---|
| **Mi cuenta** | Cualquier persona con sesión | Ver sus autenticadores, **agregar** uno (segunda passkey o llave de respaldo) y **marcar perdido** uno. No deja dar de baja el último. |
| **Ficha de persona** ("Ver ficha") | Director y administrador de seguridad | Roles y alcance (agregar, **cambiar alcance**, revocar), autenticadores (marcar perdido), sesiones abiertas, recuperación asistida y botones de **suspender, reactivar, cerrar sesiones, baja y reingreso**. |

Todas las acciones piden motivo, quedan en la bitácora y avisan por correo cuando corresponde. En local, los correos se ven en Mailpit (`http://localhost:8025`).

## 2. Reglas implementadas

| Regla (ciclo-vida) | Cómo se cumple |
|---|---|
| §8.1 Reducir acceso tiene efecto inmediato | Cambiar el alcance a uno menor o revocar un rol cierra en el acto las sesiones que lo usan, y avisa a la persona |
| §8.2 Ampliar exige autenticación reciente, motivo y aviso | Nivel C2 (15 min) con motivo; avisa a la persona y a los directores. Los roles globales los otorga sólo el director, con reautenticación inmediata (C3) |
| §8.2 Nadie amplía su propio acceso | Ninguna acción administrativa se aplica sobre la propia cuenta |
| §9 Dispositivo perdido | Se da de baja el autenticador en Keycloak, se cierran todas las sesiones y se avisa |
| §10.1 Recuperación normal con código | El método de acceso llega en el claim `amr` del token. Quien entra con un código de recuperación (`rc`) no puede operar datos hasta registrar una passkey nueva, y la app lo lleva directo a registrarla |
| §10.1 Recuperación asistida | Se registra cómo se verificó la identidad, se cierran las sesiones y hay **24 h de espera** antes de poder ejecutarla. Al ejecutarla se dan de baja todos los autenticadores y llega una invitación nueva |
| §10.2 Cuentas privilegiadas | Sólo otro director las recupera, con reautenticación inmediata. Ni seguridad ni soporte pueden hacerlo |
| §11 Suspensión y reactivación | La suspensión revoca sesiones y bloquea en Keycloak; la reactivación pide motivo y desbloquea |
| §12 Inactividad | `python -m app.seguridad.mantenimiento inactividad`: roles globales a los 30 días y el resto a los 90, con aviso 7 días antes (una vez por ciclo) |
| §14 Baja en menos de 15 minutos | Una sola operación: estado de baja, sesiones, asignaciones, recuperaciones pendientes y autenticadores revocados, bloqueo en Keycloak y verificación final. La respuesta incluye los segundos que tomó |
| §14 La identidad no se elimina | Queda como `BAJA_DEFINITIVA` para conservar la trazabilidad |
| §15 Reingreso | Invitación nueva y autenticadores nuevos; las asignaciones anteriores **no** se restauran |

### Método de acceso (`amr`)

Cada paso del flujo de Keycloak declara su método: `hwk` (llave física), `swk` (passkey) y `rc` (código de recuperación). La app decide así si una sesión es "con llave física" según lo que realmente se usó, no según el rol asignado en Keycloak. Si el token no trae `amr`, nunca se concede llave física por omisión.

## 3. Piezas

| Pieza | Archivo |
|---|---|
| Rutas del ciclo de vida y "mi cuenta" | `app/seguridad/ciclo_vida.py` |
| Avisos por correo (sin datos de clientes; sólo se registra el envío) | `app/seguridad/notificaciones.py` |
| Inactividad (tarea programable) | `app/seguridad/mantenimiento.py` |
| Recuperaciones, notificaciones y marca de autenticador pendiente | `db/control/003_ciclo_vida.sql` |
| Referencias `amr` y su mapper | `deploy/identidad/realm-facturas.json` |
| Interfaz | `app/static/acceso.js` |

## 4. Pruebas

- `tests/seguridad/test_ciclo_vida.py` (16): reglas de asignación, reducción con cierre de sesiones, baja verificada, reingreso sin permisos, reactivación, autenticador perdido, último autenticador, bloqueo tras código de recuperación, espera de 24 h, cuentas privilegiadas e inactividad.
- `tests/seguridad/test_acceso_completo.py`, con Keycloak real: entrar con código de recuperación, quedar bloqueado, registrar una passkey nueva desde la sesión y volver a operar; y tras una baja, la passkey ya no entra.

## 5. Pendiente

- **Programar** la tarea de inactividad en el servidor (una vez al día).
- **Revisión periódica de accesos** (§13): lista mensual o trimestral de accesos por confirmar.
- **Alertas en tiempo real** (auditoria-alertas §7): los eventos ya quedan marcados en la bitácora (p. ej., `USO_CODIGO_RECUPERACION`, `AUTENTICADOR_PERDIDO`, `INTENTO_ENTRE_TENANTS`), pero todavía no hay un tablero de alertas ni envío inmediato al administrador de seguridad.
- **SMTP real** para producción (fase 7).
