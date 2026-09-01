# Implementación 04 — RLS y roles mínimos del data plane

Estado: **base implementada en rama; pendiente de crear credenciales reales por tenant**.
Fecha: 2026-09-01.

## Objetivo

Conseguir que un error del backend, una consulta sin filtro o una credencial cruzada no baste para leer o escribir información de otro cliente.

## Tenant obligatorio por fila

La migración `025_tenant_rls.sql` añade `tenant_id` a todas las tablas físicas de:

- `catalog`;
- `core`;
- `ocr`;
- `ai`;
- `audit`; y
- `finance`.

Durante el aprovisionamiento controlado se verifica que no existan filas de otro tenant, se rellenan las filas existentes con el UUID inmutable de la base y cada columna queda `NOT NULL`.

Las inserciones posteriores obtienen el tenant del contexto transaccional; un valor enviado por el navegador o escrito manualmente no sustituye ese contexto.

## Row-Level Security

Cada tabla protegida utiliza:

- `ENABLE ROW LEVEL SECURITY`;
- `FORCE ROW LEVEL SECURITY`;
- una política única de tenant para lectura y modificación;
- comparación contra el contexto de la transacción; y
- segunda comparación contra la identidad provisionada del propio data plane.

Sin contexto válido el rol de ejecución ve cero filas. Un `tenant_id` distinto falla en PostgreSQL aunque la aplicación intente insertarlo explícitamente.

Las vistas de `analytics` y `finance` utilizan `security_invoker`, por lo que no heredan una capacidad de omitir RLS desde su propietario.

## Roles mínimos

La migración crea dos roles grupales sin inicio de sesión:

- `tenant_runtime`: lectura y escritura operativa, sin privilegios de estructura;
- `tenant_reports`: sólo lectura.

Ambos tienen `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOREPLICATION` y `NOBYPASSRLS`. Tampoco son propietarios de las tablas.

La auditoría funcional permite al runtime insertar eventos y actualizar únicamente los campos de confirmación de inferencia de sucursal que requiere el flujo actual. No permite borrar auditoría.

El despliegue deberá crear un login diferente por tenant y hacerlo miembro exclusivamente del rol correspondiente. Las contraseñas o certificados de esos logins permanecerán en el gestor de secretos.

## Activación de contexto

PostgreSQL rechaza `activate_request` cuando la conexión efectiva:

- es superusuario;
- posee `BYPASSRLS`;
- puede crear roles;
- es propietaria o miembro del propietario de tablas protegidas; o
- no pertenece a `tenant_runtime` o `tenant_reports`.

Después valida tenant, actor y sesión, y fija el contexto de forma local e inmutable durante la transacción.

## Evidencia automatizada

Las pruebas verifican que:

- más de veinte tablas físicas tienen `tenant_id NOT NULL` después del aprovisionamiento;
- todas tienen `ENABLE` y `FORCE ROW LEVEL SECURITY`;
- el rol runtime no ve filas antes de activar el contexto;
- el mismo rol ve las filas después de activar el tenant correcto;
- una fila con un tenant falsificado es rechazada;
- las inserciones ordinarias reciben el tenant del contexto;
- el runtime no puede borrar auditoría;
- otro tenant no puede activar el data plane;
- una credencial cruzada entre dos PostgreSQL físicamente distintos falla antes de consultar datos; y
- la aplicación demo conserva compatibilidad.

Resultado de la entrega: **146 pruebas aprobadas** con dos PostgreSQL de tenant y un plano de control aislados.

## Pendientes

1. crear logins y credenciales reales diferentes por data plane;
2. aplicar restricciones por sucursal además del aislamiento por tenant;
3. adaptar las migraciones futuras para ejecutarse con el tenant explícito;
4. enlazar las rutas financieras al router y sustituir sus conexiones actuales;
5. eliminar los actores de texto enviados por el navegador.
