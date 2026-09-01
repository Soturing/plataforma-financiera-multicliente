# Implementación 03 — Router seguro de data planes

Estado: **núcleo implementado en rama; todavía no conectado a las rutas de negocio**.
Fecha: 2026-09-01.

## Objetivo

Impedir que una selección de cliente autorizada termine, por error de configuración o manipulación, en la base de otro grupo restaurantero.

## Orden obligatorio

El router ejecuta estas comprobaciones en secuencia:

1. valida identidad, sesión, asignación, tenant, módulo, acción y sucursal;
2. si la autorización falla, no consulta el registro de secretos;
3. consulta en el plano de control únicamente una referencia opaca;
4. verifica el estado contractual del tenant;
5. obtiene las credenciales desde un registro ajeno al repositorio y al plano de control;
6. compara el tenant del registro con el tenant autorizado;
7. abre la conexión al data plane; y
8. PostgreSQL vuelve a comparar el tenant solicitado con su identidad provisionada.

Una discrepancia detiene la petición antes de ejecutar consultas financieras.

## Referencias sin secretos

`control.tenants.data_plane_reference` admite exclusivamente identificadores opacos cortos. La base de control rechaza referencias duplicadas o con caracteres que permitan rutas, URLs o traversal.

Las direcciones de PostgreSQL y raíces de archivos no se almacenan en el plano de control. El adaptador local las lee desde `config/tenants/private`, carpeta ignorada y bloqueada por la política del repositorio. En producción este adaptador deberá sustituirse por el gestor de secretos elegido.

Los entornos distintos de desarrollo, pruebas o local exigen `sslmode=verify-full` al construir el registro.

## Estado del tenant

- `ACTIVO`: permite lectura y escritura autorizadas;
- `SOLO_LECTURA`: permite únicamente operaciones de lectura;
- cualquier otro estado: no permite resolver el data plane.

La referencia secreta no se carga cuando el estado ya impide la operación.

## Identidad dentro de cada PostgreSQL

La migración `024_data_plane_identity.sql` crea una vinculación de un solo uso entre la base y un UUID de tenant.

- un data plane sin provisionar rechaza peticiones;
- la vinculación no puede actualizarse ni eliminarse;
- intentar reutilizar la base para otro tenant falla;
- cada transacción recibe tenant, actor, sesión y sucursal;
- el contexto es local a la transacción; y
- el contexto no puede reinicializarse dentro de la misma transacción.

El aprovisionamiento se ejecuta fuera de la API mediante:

```powershell
$env:FACTURAS_TENANT_MIGRATION_DATABASE_URL = '<credencial de migración obtenida del gestor de secretos>'
.\.venv\Scripts\python.exe -m app.security.data_plane_cli --tenant-id '<uuid-del-tenant>'
```

La credencial no se admite como argumento para evitar que aparezca en el historial o lista de procesos.

## Evidencia automatizada

La suite valida:

- intento de acceso a un tenant no asignado antes de consultar secretos;
- rechazo de referencias con traversal;
- rechazo de campos desconocidos en la configuración;
- TLS verificado obligatorio fuera del entorno local;
- bloqueo de escrituras en un tenant de sólo lectura;
- discrepancia entre registro y tenant autorizado;
- vinculación única e irreversible del data plane;
- rechazo del contexto de otro tenant;
- inmutabilidad del contexto transaccional; y
- acuerdo extremo a extremo entre autorización, registro y PostgreSQL.

Resultado de esta entrega: **142 pruebas aprobadas** sobre bases aisladas recreadas desde cero.

## Pendientes antes de conectar rutas financieras

1. crear credenciales separadas `tenant_runtime`, `tenant_reports` y `tenant_migrations`;
2. incorporar `tenant_id` y `FORCE ROW LEVEL SECURITY` en las tablas sensibles;
3. enlazar cada sucursal del plano de control con su UUID del data plane;
4. sustituir actores recibidos del navegador por la identidad de la sesión;
5. enlazar cada ruta con su acción y modo de acceso;
6. separar archivos y trabajos en segundo plano por tenant; y
7. ejecutar pruebas con dos data planes simultáneos y credenciales cruzadas.

Hasta completar esos puntos, las rutas financieras siguen siendo exclusivamente parte de la demo local.
