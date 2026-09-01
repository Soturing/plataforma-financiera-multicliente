# Registro de decisiones

## D-001 — PostgreSQL como fuente de verdad

Estado: adoptada para la demo.

Motivo: integridad relacional, transacciones, restricciones, auditoría y vistas de consumo para Excel.

## D-002 — Separar evidencia, propuesta y dato final

Estado: adoptada.

`ocr.resultados`, `ai.interpretaciones` y `core.facturas_finales` no se mezclan ni se sobrescriben.

## D-003 — La IA no escribe SQL libre

Estado: adoptada.

La IA devuelve una estructura validada. El backend aplica operaciones permitidas y parametrizadas.

## D-004 — Revisión humana dentro de la aplicación

Estado: adoptada.

La bandeja de revisión es una interfaz de negocio; PostgreSQL conserva su estado y auditoría.

## D-005 — Carga web antes de WhatsApp

Estado: adoptada para v0.1.

Permite probar el núcleo sin sumar autenticación, webhooks, plantillas y operación de WhatsApp Business.

## D-006 — Excel consume analytics

Estado: adoptada.

Excel no accede a OCR, prompts, confianza ni correcciones. Solo consume vistas estables del esquema `analytics`.

## D-007 — Toda factura requiere revisión en el piloto

Estado: adoptada para v0.1.

Los datos recogidos permitirán diseñar posteriormente umbrales de aprobación automática con evidencia.

## D-008 — Los capturistas pueden consultar los datos de sus asignaciones

Estado: decisión provisional para la primera versión del sistema de permisos.

Los capturistas podrán consultar por defecto la información completa de los módulos, grupos restauranteros y sucursales a los que estén asignados. En la primera versión no se aplicarán restricciones adicionales de consulta por campo sensible; por ejemplo, ocultar importes, salarios, ganancias, recetas o costos dentro de un módulo autorizado.

Esta decisión no concede acceso general a la plataforma. La consulta seguirá limitada por:

- membresía activa en el grupo restaurantero;
- módulos y sucursales asignados;
- estado activo del usuario y de la asignación;
- validación de autorización en el servidor; y
- registro de la actividad en auditoría.

El permiso de consulta no incluye automáticamente exportar, eliminar, aprobar, modificar permisos, administrar usuarios ni acceder a otros grupos restauranteros.

El modelo conservará la capacidad de introducir posteriormente restricciones de consulta por módulo, campo, sensibilidad o usuario, sin rediseñar la arquitectura de autorización.

Esta decisión deberá revisarse si se detectan consultas masivas, abuso interno, requisitos contractuales de un cliente o datos cuya exposición no sea necesaria para el trabajo del capturista.

## D-009 — Matriz funcional de permisos como línea base

Estado: adoptada para el diseño del sistema de usuarios y roles; todavía no implementada.

La matriz aprobada separa consulta, operación, aprobación, exportación, administración y auditoría. El director conserva alcance global auditado; los capturistas operan únicamente dentro de sus asignaciones; el administrador de seguridad no recibe acceso financiero por defecto; y los usuarios del cliente permanecen limitados a su propio grupo restaurantero.

La definición completa se conserva en `docs/seguridad/matriz-permisos.md`.

## D-010 — Registro inicial de amenazas y umbral de salida

Estado: adoptada para el diseño de seguridad; todavía no implementada.

Se adopta un registro inicial de 30 amenazas y una evaluación de impacto por probabilidad. Los riesgos iniciales de 12 a 16 bloquean la salida a producción hasta contar con controles, detección, respuesta, pruebas y riesgo residual documentado.

El registro completo se conserva en `docs/seguridad/registro-amenazas.md`.

## D-011 — Catálogo inicial de ocho roles

Estado: adoptada para el diseño de seguridad; todavía no implementada.

El sistema comienza con ocho roles: director de la consultora, administrador de seguridad, capturista, responsable del cliente, finanzas del cliente, operador de sucursal, soporte técnico e integración API. No se crean inicialmente roles de supervisor, capturista sénior o auditor independiente.

El catálogo completo se conserva en `docs/seguridad/catalogo-roles.md`.

## D-012 — Catálogo de quince módulos de autorización

Estado: adoptada para el diseño de seguridad; todavía no implementada.

Se adoptan quince fronteras de autorización: Documentos, Comprobantes internos, Proveedores, Catálogos contables, Ventas, Finanzas, Reportes, Nómina, Inventarios, Recetas, Administración de clientes, Identidades y accesos, Auditoría y seguridad, Integraciones y Operación técnica.

La nómina detallada permanece separada de Finanzas; Finanzas sólo puede mostrar su importe agregado. Inventarios y Recetas se reservan desde ahora aunque todavía no estén implementados.

El catálogo completo se conserva en `docs/seguridad/catalogo-modulos.md`.

## D-013 — Cuatro niveles para acciones sensibles

Estado: adoptada para el diseño de seguridad; todavía no implementada.

Las acciones se clasifican en operación ordinaria, controlada, sensible y crítica. La reautenticación inmediata se concentra en exportaciones masivas, reportes entre clientes, roles globales, recuperación privilegiada, credenciales de integración, soporte con contenido, administración del tenant y cambios globales de seguridad.

La primera versión no exige doble aprobación, pero conserva una política configurable para incorporarla posteriormente.

La definición completa se conserva en `docs/seguridad/acciones-sensibles.md`.

## D-014 — Auditoría inmutable sin duplicar contenido sensible

Estado: adoptada para el diseño de seguridad; todavía no implementada.

Se separan auditoría inmutable, historial de versiones y logs técnicos. La identidad del actor proviene siempre de la sesión. La bitácora registra metadatos, decisiones, accesos sensibles y referencias de versión, pero no copia contraseñas, tokens, secretos, archivos, nóminas, recetas ni cuerpos completos de peticiones.

Los periodos iniciales de retención quedan sujetos a validación contractual y legal antes de producción.

La definición completa se conserva en `docs/seguridad/auditoria-alertas.md`.

## D-015 — Ciclo de vida sin contraseñas de respaldo silenciosas

Estado: adoptada para el diseño de seguridad; todavía no implementada.

Se separan los estados de identidad, membresía, autenticador y sesión. Las cuentas utilizan passkeys; los roles privilegiados requieren dos llaves físicas. La recuperación no depende sólo del correo y una baja revoca inmediatamente sesiones, autenticadores, membresías y exportaciones pendientes sin eliminar la trazabilidad histórica.

La definición completa se conserva en `docs/seguridad/ciclo-vida-usuarios.md`.

## D-016 — Data plane aislado por grupo restaurantero

Estado: arquitectura objetivo adoptada; todavía no implementada.

Se adopta un plano de control compartido que no almacena información financiera y un data plane aislado por tenant. Cada grupo restaurantero tiene backend, PostgreSQL, archivos, claves, caché, colas, integraciones y respaldos propios.

Los reportes globales consultan APIs internas de sólo lectura y reciben métricas agregadas; no se crea una base central permanente con los datos de todos los clientes.

La definición completa se conserva en `docs/seguridad/arquitectura-aislamiento.md`.

## D-017 — Autenticación mediante proveedor OIDC y passkeys

Estado: adoptada e iniciada el 2026-08-31.

La aplicación no almacenará contraseñas ni implementará WebAuthn directamente. Un proveedor de identidad maduro administrará passkeys y llaves físicas. El backend aceptará únicamente tokens OIDC firmados, con algoritmo asimétrico permitido explícitamente, emisor, audiencia, expiración, fecha de emisión, fecha de autenticación y sesión verificadas.

Los roles y asignaciones no se confían al token: se consultan en el plano de control para que una revocación tenga efecto inmediato.

## D-018 — Base separada para el plano de control

Estado: primera migración implementada el 2026-08-31.

Las identidades, sesiones, tenants, asignaciones y auditoría de seguridad se almacenan en una base PostgreSQL diferente de los datos financieros. El plano de control no puede contener facturas, ventas, nómina, inventarios, recetas, archivos ni métricas financieras.

La implementación y sus pendientes se documentan en `docs/seguridad/implementacion-01-cimentacion.md`.

## D-019 — Primer director mediante instalación de un solo uso

Estado: implementada en rama el 2026-08-31; pendiente de ejecución real.

El primer director no se crea desde una ruta pública ni mediante contraseña de fábrica. Un comando fuera de línea genera una credencial aleatoria de 30 minutos, conserva únicamente su resumen y la consume al registrar una identidad nominativa con dos referencias distintas de llaves físicas.

## D-020 — Revocación inmediata mediante estado y sello de seguridad

Estado: implementada en rama el 2026-08-31.

Suspender una identidad rota su sello de seguridad, revoca todas sus sesiones, suspende sus asignaciones y cancela invitaciones pendientes en una sola transacción. Las sesiones propias pueden revocarse sin privilegios globales; revocar sesiones ajenas continúa siendo una acción administrativa C2.

Los detalles se conservan en `docs/seguridad/implementacion-02-ciclo-identidades.md`.

## D-021 — Resolución autorizada y doble identidad de tenant

Estado: núcleo implementado en rama el 2026-09-01.

Las credenciales de cada data plane se resuelven únicamente después de autorizar identidad, sesión, asignación y selección de tenant. El plano de control conserva una referencia opaca, nunca la credencial. La configuración externa y el PostgreSQL destino deben declarar el mismo UUID autorizado; la vinculación interna de la base es de un solo uso e inmutable.

Los detalles y los controles todavía pendientes se conservan en `docs/seguridad/implementacion-03-router-data-plane.md`.

## D-022 — Tenant obligatorio y RLS forzada dentro de cada silo

Estado: implementada en rama el 2026-09-01; pendiente de credenciales reales de despliegue.

Aunque cada cliente posee un PostgreSQL separado, todas las tablas sensibles conservan también el UUID inmutable del tenant y aplican `FORCE ROW LEVEL SECURITY`. Los roles runtime y reportes no pueden omitir RLS ni modificar estructura; una conexión privilegiada o propietaria es rechazada al intentar activar un contexto de aplicación.

Los detalles se conservan en `docs/seguridad/implementacion-04-rls-credenciales.md`.
