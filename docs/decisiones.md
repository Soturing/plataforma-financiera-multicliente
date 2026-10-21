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

## D-017 — Nueve categorías de gasto y sin centros de costo

Estado: adoptada e implementada (migración 024).

Las categorías son una lista fija: Gastos fijos, Nómina, Comisiones, Variables operativos, Gastos imprevistos, Mantenimiento, Gasolina, Gastos Barra y Gastos Restaurantes. Las subcategorías son editables dentro de cada categoría; Variables operativos no lleva subcategorías predefinidas porque cada sucursal tiene conceptos distintos.

Los centros de costo se eliminan: la separación Barra/Restaurante ya la expresan las categorías Gastos Barra y Gastos Restaurantes, y mantener ambas obligaba a clasificar dos veces lo mismo.

Cada categoría declara su `tipo_costo` (fijo o variable) y si admite facturas. Fijos y Nómina cuentan como gastos fijos en el Estado de Resultados y el punto de equilibrio; todas las demás, como costos variables. Nómina y Comisiones no se capturan con facturas.

Lista de gastos fijos con alta previa: implementada (migración 025, `catalog.gastos_fijos`). Comisiones con proyección y cierre real mensual: implementadas (migración 026). Nómina con captura manual semanal por sucursal: implementada (migración 027). Detalle en `docs/categorias-gastos.md`.

Cambio de contrato: las vistas `analytics.*` ya no exponen la columna `centro_costo` y `analytics.movimientos_gasto` añade `categoria_clave` y `tipo_costo`. Los libros de Excel que consuman esas vistas deben actualizarse.

## D-018 — Usuarios y seguridad se construyen desde cero sobre esta línea

Estado: adoptada (2026-10-18).

La rama `codex/security-foundation` se considera código legado y no se reutiliza ni se porta. El sistema de usuarios, permisos, aislamiento y auditoría se construye sobre la línea de desarrollo hacia el MVP, con migraciones a partir de la 032, y se verifica contra los documentos de `docs/seguridad/`.

Primera entrega: multi-tenant completo desde el inicio (plano de control, data plane por cliente, RLS, sesiones, roles y auditoría), no una versión de un solo cliente que luego se migre.

## D-019 — Despliegue en servidor propio con Docker

Estado: adoptada (2026-10-18).

El primer cliente se despliega en un servidor o VPS propio con Docker. D-016 se materializa así:

- plano de control: servicio propio, PostgreSQL de control y proveedor de identidad, en una red Docker separada;
- data plane por cliente: contenedores propios de backend y workers OCR, PostgreSQL propio, volumen de archivos propio y red Docker propia sin ruta hacia otros clientes;
- un proxy inverso con TLS es el único punto expuesto a internet.

No existe un KMS gestionado, por lo que el gestor de secretos y las claves de cifrado por cliente se resuelven en la fase correspondiente del plan (`docs/seguridad/plan-implementacion.md`).

## D-020 — Excepción temporal: una persona con los dos roles globales

Estado: adoptada como excepción temporal (2026-10-18).

Al inicio, una misma persona ocupará Director y Administrador de seguridad. Esto contradice la separación de funciones del catálogo de roles, por lo que se acepta solo como excepción temporal con estas compensaciones:

- una sola identidad con dos asignaciones explícitas; cada sesión opera con **un solo rol activo**, elegido al entrar, y cambiar de rol exige reautenticación;
- la auditoría registra siempre el rol efectivo; nunca se suman los permisos de ambos roles en una sesión;
- se mantienen las dos llaves físicas FIDO2 exigidas para cuentas privilegiadas;
- el resumen semanal de auditoría se copia fuera del servidor, porque no hay una segunda persona que lo revise;
- el sistema no se diseña alrededor de la excepción: al darla de baja basta con retirar una asignación.

La excepción termina al incorporar a una segunda persona con rol global o antes de incorporar al segundo cliente, lo que ocurra primero.

## D-021 — Keycloak como proveedor de identidad

Estado: adoptada (2026-10-18); sujeta a la prueba técnica de la fase 1.

Se autoaloja Keycloak con su propio PostgreSQL dentro del plano de control (D-019). Se elige porque permite, sin código propio, exigir llaves físicas con atestación a los roles globales y passkeys del dispositivo a los roles operativos, sin contraseña de respaldo.

Keycloak sólo demuestra la identidad. Sesiones, membresías, roles, alcance y auditoría pertenecen al plano de control de la aplicación, que recibe la identidad mediante OIDC con código y PKCE del lado del servidor.

Si la prueba técnica de la fase 1 no confirma alguno de sus puntos, la decisión se revisa antes de iniciar la fase 2. Comparación y criterios en `docs/seguridad/plan-implementacion.md`.

## D-022 — Modo de acceso abierto durante la transición

Estado: adoptada como transitoria (2026-10-18).

`FACTURAS_ACCESO_MODO=abierto` conserva el uso sin sesión de las pantallas existentes mientras las personas registran sus llaves y passkeys. Quien inicia sesión opera siempre con sus permisos, y su identidad se registra como autor. Las rutas de identidades, auditoría, clientes y operación técnica exigen sesión incluso en modo abierto.

El modo seguro (`FACTURAS_ACCESO_MODO=seguro`) exige sesión en toda ruta de datos. Es obligatorio antes de producción y antes de incorporar al segundo cliente.

## D-023 — El 8010 sirve la rama de seguridad sobre la base compartida

Estado: resuelta por D-024 (2026-10-18): el 8010 sirve el data plane propio de `GRUPO-DEMO` (5440); la 5434 queda sólo para `migrate-legacy`.

El puerto 8010 sirve la rama `claude/roadmap-usuarios-seguridad-8e43ba` (toda la línea `migrate-legacy` más usuarios y seguridad), con la misma base de negocio (5434) y los mismos archivos. El plano de control y Keycloak tienen bases propias.

La fase 5 (RLS forzado y cuenta sin propiedad) no se aplica sobre la base compartida, porque dejaría inoperable la línea `migrate-legacy` si se vuelve a ejecutar contra ella. Antes de la fase 5 hay que decidir entre fusionar esta rama en `migrate-legacy` o darle a esta rama su propia base.

## D-024 — Tenant = administración; restaurantes y sucursales estratificados en su base

Estado: adoptada (2026-10-18).

Un tenant es una administración o grupo restaurantero (el cliente de la consultora), no un restaurante. Cada tenant tiene su propio stack (vía 4 de D-016 y D-019): backend, workers, PostgreSQL, archivos, red y credenciales propios, generados desde una plantilla.

Dentro de un tenant, todos sus restaurantes y sucursales comparten la base, estratificados así:

- `catalog.restaurantes` formaliza la jerarquía restaurante → sucursal, que hoy es texto libre;
- las asignaciones pueden dar alcance por restaurante completo o por sucursal, y se guardan en tablas pivote con integridad referencial;
- RLS forzado por tenant y por sucursal es la segunda barrera dentro de la base: aunque el código omita un filtro, la base no devuelve filas fuera del alcance.

La fase 5 crea el primer stack (`GRUPO-DEMO`) con una copia de la base 5434, que queda intacta para la línea `migrate-legacy`. El 8010 pasa a usar ese stack. Si un restaurante cambia de dueño, sus datos se extraen a un stack nuevo mediante un procedimiento puntual.

## D-025 — OpenBao, claves por cliente y respaldos cifrados

Estado: adoptada (2026-10-18). Detalle en `docs/seguridad/fase7-secretos-respaldos.md`.

- **Secretos y claves:** OpenBao autoalojado con **desbloqueo manual** (3 llaves, se necesitan 2). Tras cada reinicio la app no obtiene secretos hasta que el director lo abre. El token raíz se revoca al inicializar.
- **Claves por cliente:** dos claves Transit por cliente (`datos` y `respaldos`), no exportables, con rotación y bitácora de uso. Cada cliente tiene identidades propias para su app y sus respaldos, que sólo acceden a lo suyo.
- **Respaldos:** restic, un repositorio por cliente, diario (pérdida máxima 24 h). Destino S3 con Object Lock y retención por ciclo de vida del bucket (30 diarios, 12 mensuales, 7 anuales, sujeto a validación legal). En desarrollo, rest-server en modo sólo anexado. Prueba de restauración trimestral en una base desechable.
- **Archivos en reposo:** cifrado por cliente a nivel de sistema de archivos (gocryptfs) en el servidor, con su clave envuelta por la clave `datos` del cliente. Sustituye la propuesta inicial de cifrar en la app, que habría obligado a dejar copias descifradas temporales en unos 80 puntos de lectura.
- **VPS:** proveedor por definir; el diseño no depende de uno en particular.

## D-026 — Despliegue: una imagen, un stack por cliente y archivos con gocryptfs

Estado: adoptada (2026-10-18). Detalle en `docs/seguridad/despliegue-servidor.md`.

- Una sola imagen del backend para todos los clientes; cada cliente corre su app y sus workers en su propio proyecto Docker con su base en una red propia.
- El contenedor obtiene sus secretos de OpenBao al arrancar con la identidad de la app del cliente y borra esa credencial antes de lanzar la app; corre sin privilegios.
- Los archivos de cada cliente se cifran en el host con gocryptfs; el contenedor sólo recibe la vista descifrada.
- Caddy es el único servicio público (TLS automático); cada cliente tiene su subdominio y Keycloak sólo expone la pantalla de acceso.
- Tras un reinicio, una persona abre OpenBao y levanta los clientes (`deploy/servidor/arrancar.sh`).
- Recomendación de proveedores: VPS en Hetzner (EE. UU. Este) salvo requisito de residencia en México (AWS mx-central-1); respaldos en Backblaze B2 con Object Lock, proveedor distinto al del VPS.

## D-027 — Auditoría de sólo anexado y facturas con correcciones

Estado: adoptada (2026-10-19). Detalle en `docs/roadmap-producto.md` §2.3 y §3.8.

- **Una factura con correcciones no se borra:** `audit.correcciones` referencia facturas y revisiones con `ON DELETE RESTRICT` (antes `CASCADE` borraba el historial). La bandeja responde 409.
- **Auditoría de sólo anexado también para la propietaria:** triggers en `audit.correcciones`, `audit.cambios_catalogo` y `audit.documentos_eliminados` (y sin `DELETE` en `audit.aprendizajes`). La única salida es que la propietaria declare `audit.purga = 'on'` en su sesión (limpieza de pruebas y futura política de retención).
- **Tolerancia en centavos** del futuro `CHECK` de totales: flexible hasta tener datos de producción; se fija después.

## D-028 — El acceso es seguro por defecto; el modo abierto es sólo una opción de desarrollo

Estado: adoptada (2026-10-19). Reemplaza el carácter transitorio de D-022.

- `FACTURAS_ACCESO_MODO` vale `seguro` si no se declara: toda ruta de datos exige sesión.
- El modo abierto (`abierto`) sigue disponible, pero hay que escribirlo a propósito en el `.env` de desarrollo. Con `FACTURAS_ENVIRONMENT=produccion` la aplicación se niega a arrancar en modo abierto.
- Las pruebas fijan `abierto` en `tests/conftest.py` para ejercer las rutas de datos sin sesión; las de modo seguro lo activan en su propia fixture.
- Consecuencia práctica: un `.env` sin esa variable deja de abrir el 8010 sin sesión. Para revisar pantallas sin iniciar sesión, agregar `FACTURAS_ACCESO_MODO=abierto` al `.env` de desarrollo.

## D-029 — Identidad estable por trigger, copiada de la sesión

Estado: adoptada (2026-10-19). Detalle en `docs/roadmap-producto.md` §2.3 punto 3.

- Las identidades viven en el plano de control (otra base), así que no hay clave foránea: cada columna `*_por` (texto, la etiqueta que se muestra) gana un `*_por_id uuid` con el identificador estable.
- La app declara `app.identidad` en las opciones de la conexión (`app/database.py`) y el trigger `seguridad.completar_identidad` lo copia al escribir o al cambiar la etiqueta. El valor nunca viaja en el cuerpo de la petición.
- Sin sesión el `_id` queda vacío (no se inventa) y las filas anteriores no se rellenan. `core.trabajos_ocr.reservado_por` se excluye: identifica a un worker, no a una persona.
- `tenant_runtime` recibe `statement_timeout` de 120 s e `idle_in_transaction_session_timeout` de 60 s (`tenants crear_roles` y `tenants migrar`).

## D-030 — ClamAV obligatorio en el servidor, piso de cobertura, cuotas y desglose que no cuadra

Estado: adoptada (2026-10-20), a petición del responsable del producto.

- **Antivirus:** sí. ClamAV corre como servicio compartido del plano de control; en el servidor el modo es `obligatorio` (si no responde, no se acepta el archivo) y en desarrollo `apagado`. Detalle en `app/antivirus.py`.
- **Cobertura:** el responsable desconoce el estándar; se fija un **piso de 60 %** (hoy 66 %) que sólo se sube. Para código nuevo se recomienda 80 %, pero no se exige.
- **Desglose que no cuadra:** se **mantiene** la regla actual: la factura puede aprobarse «verificando el total». No se añade un `CHECK` de totales en la base.
- **Cuotas por cliente:** 10 000 documentos al día (≈ 3 veces el volumen esperado) y 50 GB de archivos, ajustables por cliente.
- **Retención del borrado lógico (para el diseño de la etapa siguiente):** 5 años, por la obligación fiscal de conservar los comprobantes.
