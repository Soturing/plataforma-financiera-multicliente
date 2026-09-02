# Implementación 09 — Duplicados con frontera de sucursal

Estado: **implementado en código y validado en bases sintéticas; migración local pendiente de ventana operativa**.
Fecha: 2026-09-02.

## Alcance

Se incorporan al modo seguro:

- `GET /api/v1/duplicados`;
- `GET /api/v1/duplicados/{duplicado_id}/archivo`;
- `POST /api/v1/duplicados/descartar`.

El total conectado asciende a 17 de 59 rutas de negocio. Las otras 42 continúan cerradas por defecto.

## Pertenencia inequívoca

La migración `026_duplicate_branch_scope.sql` añade `sucursal_id` obligatorio a cada detección. Para registros anteriores usa primero la sucursal de la factura duplicada y, cuando sólo existe un archivo por hash, la sucursal de la factura original. Las detecciones nuevas por hash guardan la sucursal a la que se intentó cargar el archivo; las detecciones por UUID fiscal conservan la sucursal de la factura duplicada.

## Coincidencias entre sucursales

Una coincidencia puede relacionar tres alcances: sucursal destino del archivo detectado, sucursal de la factura original y sucursal de la factura duplicada, si existe.

- Una consulta limitada a sucursal sólo devuelve el caso cuando todos los alcances existentes coinciden con la sucursal autorizada.
- Una coincidencia cruzada no confirma al capturista que existe un documento en otra sucursal ni revela nombre, proveedor, importe o archivo.
- Un responsable con alcance total sobre las sucursales del tenant puede revisar el caso completo.
- Abrir o descartar autoriza todos los alcances antes de leer o modificar el registro; no se realizan cambios parciales antes de esa comprobación.

## Acción de descarte

Descartar se eleva a control C2 porque rechaza una factura y elimina el archivo detectado. Exige autenticación reciente, escribe el UUID del actor de la sesión aunque el navegador envíe otro nombre y sólo elimina archivos ubicados bajo la raíz de almacenamiento del tenant.

## Evidencia

- La suite aislada general alcanzó `143 passed`, `19 skipped` antes de vincular el data plane de la prueba segura.
- La prueba HTTP con login restringido `tenant_runtime` validó lista, apertura y descarte del duplicado, actor de sesión, tenant, sucursal, RLS, almacenamiento y auditoría.
- La prueba de coincidencia cruzada confirmó que las colecciones de ambas sucursales quedan vacías mientras la vista autorizada del tenant completo conserva el caso.

## Despliegue local pendiente

La base local en uso no se migró ni se reinició mientras el operador aprobaba facturas. Antes de arrancar esta versión sobre un volumen existente se debe respaldar el data plane, ejecutar la migración 026 durante una ventana controlada y verificar el conteo de filas sin sucursal. Los data planes nuevos la reciben automáticamente mediante `compose.yaml`.
