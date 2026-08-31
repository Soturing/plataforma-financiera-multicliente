# Ciclo de vida de usuarios

Estado: línea base funcional aprobada; todavía no implementada.
Fecha de aprobación: 2026-08-30.

## 1. Entidades independientes

```text
Identidad
├── Quién es la persona
│
Membresía
├── A qué cliente pertenece o está asignada
│
Rol y alcance
├── Qué puede hacer y en qué sucursales
│
Autenticadores
├── Con qué passkeys o llaves demuestra su identidad
│
Sesiones
└── Qué accesos permanecen abiertos
```

El estado de una identidad no sustituye el estado de sus membresías, autenticadores o sesiones.

## 2. Estados de identidad

```text
INVITADA
   ↓
REGISTRO_PENDIENTE
   ↓
ACTIVA
   ├── BLOQUEADA_SEGURIDAD
   ├── SUSPENDIDA
   └── BAJA_DEFINITIVA
```

- **Invitada:** se creó la invitación, pero no fue utilizada.
- **Registro pendiente:** la identidad fue verificada; faltan autenticadores.
- **Activa:** puede autenticarse según sus membresías.
- **Bloqueada por seguridad:** bloqueo automático o preventivo.
- **Suspendida:** decisión administrativa; no puede iniciar sesión.
- **Baja definitiva:** relación terminada; no se reactiva automáticamente.

La baja no elimina el identificador utilizado por la auditoría.

## 3. Estados de membresía

```text
PENDIENTE
ACTIVA
SUSPENDIDA
EXPIRADA
REVOCADA
```

Una persona puede conservar su identidad activa y perder acceso solamente a un cliente.

## 4. Invitación

El director o administrador de seguridad:

1. registra a la persona;
2. selecciona rol;
3. selecciona tenant;
4. selecciona módulos;
5. selecciona sucursales;
6. configura permisos condicionados;
7. define vigencia;
8. revisa el resumen; y
9. envía una invitación individual.

La invitación:

- es de un solo uso;
- caduca en 24 horas;
- está vinculada al correo y asignación originales;
- no revela datos del cliente;
- no permite cambiar el tenant; y
- se invalida cuando se utiliza o reemplaza.

Una invitación vencida se reemplaza por una nueva; no se reactiva el mismo enlace.

## 5. Registro de autenticadores

### 5.1 Director y administrador de seguridad

Requieren:

- llave física FIDO2 principal;
- segunda llave física de respaldo;
- registro desde un dispositivo confiable; y
- ausencia de recuperación ordinaria por correo.

### 5.2 Capturistas

Requieren:

- passkey principal;
- segundo autenticador o códigos de recuperación; y
- recomendación de llave física cuando trabajen con varios clientes.

### 5.3 Usuarios del cliente

Requieren:

- passkey principal;
- passkey de respaldo o códigos de recuperación; y
- ausencia de preguntas secretas.

No se habilita una contraseña como alternativa silenciosa cuando falla una passkey.

## 6. Primer acceso

Después de registrar el autenticador, el usuario ve:

- rol;
- clientes;
- módulos;
- sucursales;
- permisos condicionados;
- fecha de expiración; y
- dispositivos registrados.

La activación y el resumen quedan auditados. El usuario y el director reciben notificación.

## 7. Sesiones

### 7.1 Roles privilegiados

Director y administrador de seguridad:

- inactividad máxima de 15 minutos;
- duración absoluta de 8 horas;
- máximo recomendado de dos dispositivos activos;
- sin opción permanente de recordar la sesión; y
- reautenticación para acciones C3.

### 7.2 Roles operativos

Capturistas y usuarios del cliente:

- inactividad máxima de 30 minutos;
- duración absoluta de 12 horas;
- máximo recomendado de tres dispositivos activos; y
- reautenticación según acciones C2 y C3.

Todas las sesiones:

- utilizan cookies seguras;
- pueden revocarse individualmente o en conjunto;
- se invalidan ante una baja;
- se revisan contra permisos vigentes; y
- no conservan hasta su expiración una autorización retirada.

## 8. Cambios de rol o asignación

### 8.1 Reducción de acceso

Tiene efecto inmediato:

- revocar sesiones afectadas;
- limpiar caché del usuario;
- cancelar exportaciones fuera del nuevo alcance;
- bloquear operaciones en curso antes de confirmar cambios; y
- notificar al usuario.

### 8.2 Ampliación de acceso

Requiere:

- autenticación reciente del administrador;
- resumen de nuevos privilegios;
- motivo;
- auditoría; y
- notificación al usuario y director.

Un administrador no puede ampliar su propio acceso global.

## 9. Dispositivo perdido

El usuario o administrador puede:

1. marcar el autenticador como perdido;
2. revocar sus sesiones;
3. conservar otros autenticadores válidos;
4. revisar actividad reciente;
5. suspender la identidad si existe duda; y
6. registrar un nuevo autenticador después de verificar identidad.

Perder un teléfono no obliga a depender del correo como único método de recuperación.

## 10. Recuperación de cuenta

### 10.1 Recuperación normal

Orden de preferencia:

1. segunda passkey;
2. llave física de respaldo;
3. código de recuperación de un solo uso; y
4. recuperación asistida.

La recuperación asistida:

- no utiliza únicamente un enlace de correo;
- verifica identidad por un canal previamente registrado;
- aplica una espera inicial de 24 horas;
- notifica mediante los canales anteriores;
- revoca sesiones existentes;
- revoca autenticadores considerados perdidos; y
- registra el procedimiento completo.

### 10.2 Cuentas privilegiadas

Director y administrador de seguridad utilizan la llave física de respaldo.

La pérdida de ambas llaves no se resuelve mediante soporte ordinario. Activa un procedimiento de incidente con verificación reforzada y espera de seguridad. Soporte no puede recuperar unilateralmente una cuenta privilegiada.

## 11. Bloqueo y suspensión

### 11.1 Bloqueo automático

Puede ocurrir por:

- intentos fallidos repetidos;
- reutilización de sesión revocada;
- dispositivo o ubicación anormal;
- comportamiento de extracción masiva; o
- intento entre tenants.

No elimina membresías y puede liberarse después de revisión.

### 11.2 Suspensión administrativa

- revoca todas las sesiones;
- impide nuevos accesos;
- mantiene auditoría e historial;
- conserva tareas pendientes;
- requiere motivo; y
- notifica al usuario.

La suspensión contractual de un cliente se maneja separadamente del estado individual de sus usuarios.

## 12. Inactividad

Política inicial:

- roles globales sin actividad durante 30 días: suspensión preventiva;
- capturistas y usuarios de clientes sin actividad durante 90 días: suspensión preventiva;
- aviso siete días antes;
- reactivación mediante passkey y revisión de asignaciones; e
- integraciones sin uso durante 90 días: revisión y posible revocación.

## 13. Revisión periódica

- roles globales: revisión mensual;
- asignaciones de capturistas: revisión trimestral;
- usuarios de clientes: revisión trimestral;
- integraciones: revisión trimestral;
- permisos de exportación: revisión mensual; y
- accesos de soporte: revisión después de cada uso.

El director recibe una lista de accesos que deben confirmarse o revocarse.

## 14. Baja de colaborador

La baja ejecuta una operación central:

1. suspender identidad;
2. revocar sesiones;
3. revocar autenticadores;
4. revocar membresías;
5. cancelar exportaciones pendientes;
6. revocar credenciales técnicas bajo su responsabilidad;
7. transferir documentos y tareas pendientes;
8. preservar auditoría;
9. notificar al director; y
10. verificar que el acceso ya no funciona.

Objetivo operativo: completar la revocación en menos de 15 minutos desde que se inicia la baja.

La identidad no se elimina porque rompería la trazabilidad histórica.

## 15. Reingreso

Si una persona vuelve a la organización:

- se verifica nuevamente su identidad;
- se registran nuevos autenticadores;
- se revisan conflictos con identidades anteriores;
- no se restauran membresías antiguas automáticamente;
- se crean nuevas asignaciones; y
- se conserva la relación con la auditoría histórica.

## 16. Primer director

El primer director se crea mediante un procedimiento controlado de instalación:

- identidad nominativa;
- registro de dos llaves físicas;
- credencial temporal de instalación invalidada inmediatamente;
- evento de auditoría inicial; y
- verificación de que no quede una cuenta genérica o contraseña de fábrica.

## 17. Parámetros configurables iniciales

- invitación: 24 horas;
- sesión privilegiada inactiva: 15 minutos;
- sesión operativa inactiva: 30 minutos;
- duración absoluta privilegiada: 8 horas;
- duración absoluta operativa: 12 horas;
- suspensión preventiva global: 30 días sin actividad; y
- suspensión preventiva normal: 90 días sin actividad.
