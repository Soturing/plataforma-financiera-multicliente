# Plan de implementación: usuarios, acceso y aislamiento

Estado: aprobado (2026-10-18). Fase 1 completada ([fase1-identidad.md](fase1-identidad.md)); fases 2 a 4 implementadas en modo abierto ([fases2-4-acceso.md](fases2-4-acceso.md)); fase 5 pendiente de D-023.

Base: D-016, D-018, D-019, D-020, D-021 y los documentos de esta carpeta. Cada fase termina con pruebas automáticas y sólo se da por cerrada cuando sus criterios de salida pasan.

## 1. Proveedor de identidad: Keycloak (D-021)

El roadmap prohíbe construir criptografía propia. El proveedor se autoaloja en el mismo servidor (D-019).

| Criterio | Keycloak | ZITADEL | authentik |
|---|---|---|---|
| Passkeys en el formulario de acceso | Sí (26.4) | Sí, enfoque *passkey-first* | Sí (etapa WebAuthn) |
| Exigir llave física por rol (lista de AAGUID, atestación) | Sí, políticas WebAuthn y flujos condicionados por rol | Limitado | Posible con flujos y scripts |
| Códigos de recuperación | Sí (26.3), pensados como respaldo de OTP; falta confirmar su uso con cuentas sólo-passkey | Sí | Sí |
| Configuración como código (export de realm, Terraform) | Sí | Sí | Sí (blueprints) |
| Recursos aproximados | Java; ~1–2 GB RAM | Go; ligero | Python; ~2 GB RAM |
| Madurez y auditorías públicas | La más amplia | Alta | Media |

**Elegido: Keycloak (D-021).** Es el único que permite, sin código propio, exigir llaves físicas al Director y al Administrador de seguridad y passkeys del dispositivo al resto (`ciclo-vida-usuarios.md` §5). El costo es su consumo de memoria.

La fase 1 incluye una prueba técnica que debe confirmar, antes de seguir: registro con passkey, exigencia de llave física por rol, reautenticación forzada (`max_age=0`) con el nivel de autenticación en el token, y el comportamiento de los códigos de recuperación en cuentas sin contraseña.

## 2. Reparto de responsabilidades

```text
Proveedor de identidad   → demuestra quién es la persona (passkey o llave física)
Plano de control         → sesiones, membresías, roles, alcance, auditoría de seguridad
Data plane del cliente   → vuelve a verificar el contexto firmado y aplica RLS
```

- La aplicación usa el patrón *backend for frontend*: flujo OIDC con código y PKCE en el servidor y cookie de sesión `HttpOnly`, `Secure`, `SameSite=Strict`. El navegador nunca recibe tokens del proveedor.
- Las sesiones viven en la base de control. Así se cumplen tiempos distintos por rol (15/30 min de inactividad, 8/12 h absolutas) y la revocación inmediata, que el proveedor no resuelve por rol.
- Las acciones C2 y C3 piden una nueva autenticación al proveedor y verifican en servidor la hora y el método de esa autenticación.
- El tenant nunca se toma del navegador: se deriva de la sesión, la membresía vigente y la selección validada (`arquitectura-aislamiento.md` §7).

## 3. Fases

### Fase 1 — Proveedor de identidad y prueba técnica

- Keycloak con su propio PostgreSQL en `compose`, realm versionado sin secretos.
- Flujos de acceso: passkey para roles operativos; llave física con atestación para roles globales; sin contraseña de respaldo.
- Salida: los cinco puntos de la prueba técnica de §1 verificados y documentados. **Cumplida en local** (ver [fase1-identidad.md](fase1-identidad.md)); queda la verificación manual con una llave física real.

### Fase 2 — Plano de control

- Base de control separada: identidades, tenants, sucursales del registro, membresías, asignaciones (rol, módulos, sucursales, permisos condicionados, vigencia), autenticadores (metadatos) y sesiones.
- Estados de identidad, membresía, autenticador y sesión de `ciclo-vida-usuarios.md`.
- Bitácora de auditoría de sólo anexado: rol de base distinto, sin `UPDATE`/`DELETE`, eventos encadenados por hash y detección de huecos.
- Instalación del primer director: credencial temporal invalidada al registrar las dos llaves.
- Salida: pruebas de estados, de bitácora inmutable (un intento de `UPDATE` falla) y de instalación sin cuenta genérica.

### Fase 3 — Sesiones y autenticación en la aplicación

- Inicio y cierre de sesión, selección de cliente y de rol activo (D-020), expiración por inactividad y absoluta, revocación individual y total.
- Reautenticación para C2 y C3.
- Límites de intentos y alertas de autenticación (`auditoria-alertas.md` §8).
- Salida: pruebas de expiración, revocación, reutilización de sesión revocada y reautenticación.

### Fase 4 — Autorización

- Matriz de permisos como datos: rol × módulo × acción × alcance, con denegación por defecto.
- Toda ruta declara módulo, acción y nivel C0–C3; una prueba falla si aparece una ruta sin clasificar.
- El actor sale siempre de la sesión: se eliminan campos como `revisada_por` de las peticiones.
- Salida: cada regla de `matriz-permisos.md` §11 convertida en prueba.

### Fase 5 — Data plane por cliente

- Contenedores, red, PostgreSQL, volumen de archivos y workers OCR propios por cliente; el proxy enruta al data plane del tenant de la sesión.
- Contexto firmado de corta duración entre plano de control y data plane; el data plane lo verifica antes de cada operación.
- `tenant_id` en tablas sensibles, RLS con `FORCE` y cuenta de ejecución sin propiedad de tablas ni `BYPASSRLS`; filtro adicional por sucursal.
- Migración del grupo demo actual como primer tenant y alta de un segundo tenant ficticio.
- Salida: pruebas de aislamiento con dos tenants (consultas, archivos, cola OCR, caché y credenciales cruzadas fallan).

### Fase 6 — Ciclo de vida y administración

- Invitaciones de un solo uso (24 h), primer acceso con resumen de permisos, cambios de asignación con revocación inmediata al reducir acceso.
- Dispositivo perdido, recuperación con autenticador de respaldo o códigos, y recuperación asistida con espera de 24 h.
- Suspensión, baja en menos de 15 minutos, inactividad y reingreso.
- Pantallas de administración de usuarios y de consulta de auditoría.
- Salida: pruebas de cada flujo y verificación de que el acceso deja de funcionar tras una baja.

### Fase 7 — Antes de producción

- Gestor de secretos y clave de cifrado por cliente (por decidir: OpenBao o sops + age).
- Respaldos cifrados fuera del servidor y prueba de restauración.
- Revisión de las amenazas con riesgo inicial ≥ 12 de `registro-amenazas.md` con su riesgo residual documentado.
- Prueba de penetración externa.

## 4. Pendientes de decidir

- Modelo de llave física para los roles globales (fija los AAGUID y las raíces de atestación del truststore).
- Gestor de secretos y claves por cliente.
- Canal para invitaciones y notificaciones (correo transaccional u otro).
- Dominio y certificados TLS del servidor.
- Destino de los respaldos fuera del servidor.

## 5. Referencias

- [Keycloak 26.3: códigos de recuperación como función soportada](https://www.keycloak.org/2025/07/keycloak-2630-released)
- [Keycloak 26.4: passkeys en los formularios de acceso](https://www.keycloak.org/2025/09/keycloak-2640-released)
- [Keycloak: códigos de recuperación](https://www.keycloak.org/2025/10/recovery-codes)
