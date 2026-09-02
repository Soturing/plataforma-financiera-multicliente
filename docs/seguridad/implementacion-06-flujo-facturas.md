# Implementación 06 — Primer flujo vertical seguro de facturas

Estado: **primer subconjunto conectado y probado; activación real pendiente de OIDC**.
Fecha: 2026-09-01.

## Objetivo

Demostrar sobre handlers reales que una operación financiera puede recorrer, sin confiar en datos del navegador:

```text
token OIDC → sesión vigente → permiso → tenant → sucursal → data plane → RLS → auditoría
```

## Rutas conectadas

Doce de las 59 rutas de negocio utilizan ya el acceso seguro:

- carga individual de factura;
- procesamiento simulado síncrono;
- resumen y bandeja de revisión;
- detalle, expediente y archivo original;
- catálogos requeridos por la revisión; y
- aprobación, corrección, edición posterior y rechazo.

El procesamiento OCR asíncrono no está habilitado en modo seguro todavía, porque su worker continúa usando la conexión global de la demo. Habilitarlo antes de transportar un contexto firmado de tenant y una cola aislada produciría un cruce de frontera.

## Cierre por defecto

`FACTURAS_ENFORCE_BUSINESS_SECURITY` es verdadero por defecto. Cuando está activo:

- las doce rutas conectadas exigen token, tenant y el alcance de sucursal aplicable;
- las 47 rutas restantes responden `route_not_security_integrated`;
- ninguna ruta pendiente cae silenciosamente en la base compartida de la demo; y
- una auditoría indisponible bloquea una autorización aceptada antes de ejecutar el handler.

La excepción `false` sólo se admite en `development`, `test`, `testing` o `local`. El archivo local actual la utiliza para no interrumpir la demo mientras se elige y configura el proveedor OIDC. Una configuración de producción con esa excepción es inválida.

## Identidad efectiva

En las cinco operaciones conectadas que todavía aceptan `creada_por` o `revisada_por` por compatibilidad con la interfaz local, el modo seguro ignora esos valores. Las columnas de trazabilidad reciben el UUID de la identidad cargada desde la sesión del plano de control.

La prueba integrada envía deliberadamente una identidad falsa desde el navegador y comprueba que:

- la factura conserva el UUID de la sesión;
- el tenant insertado es el tenant inmutable del data plane;
- la sucursal coincide con el alcance autorizado; y
- el evento encadenado de autorización conserva actor, sesión, tenant, sucursal, acción y `request_id` correctos.

## Alcance de sucursal

Todos los permisos de Documentos son ahora sensibles a sucursal. El encabezado `X-Branch-Id` representa el UUID físico de la sucursal y se valida dos veces:

1. el plano de control confirma que la sucursal activa pertenece al tenant; y
2. el handler resuelve la sucursal real del formulario o del recurso y vuelve a autorizarla contra las asignaciones de la sesión.

Una corrección que cambia `sucursal_id` autoriza también la sucursal destino. Los documentos `POR-ASIGNAR` se consideran una bandeja de entrada del tenant: la sucursal destino continúa siendo obligatoria para aprobar y debe pertenecer a las asignaciones del actor.

## Archivos y credenciales

La carga y lectura conectadas utilizan la raíz de archivos resuelta para el tenant, no `FACTURAS_UPLOAD_DIR`. La conexión se abre con un login restringido miembro de `tenant_runtime`; las credenciales de propietario siguen siendo rechazadas por `activate_request`.

## Evidencia

La suite completa alcanza **158 pruebas aprobadas** sobre bases sintéticas aisladas. Incluye:

- cierre de rutas no integradas;
- autenticación obligatoria en rutas integradas;
- imposibilidad de desactivar seguridad en producción;
- rechazo de sucursales no registradas o no asignadas;
- identidad del navegador ignorada;
- carga HTTP real mediante credencial runtime restringida;
- RLS y tenant insertado automáticamente;
- auditoría encadenada de la autorización; y
- credenciales cruzadas entre dos data planes rechazadas.

## Pendiente antes de activar este modo

1. elegir y configurar el proveedor OIDC con passkeys;
2. aprovisionar director, tenants, sucursales, usuarios y secretos reales;
3. adaptar la interfaz para enviar token, tenant y sucursal;
4. retirar definitivamente los campos de actor del contrato;
5. hacer tenant-aware los workers, colas y OCR;
6. conectar las otras 47 rutas; y
7. ejecutar pruebas de penetración y operación.
