# Implementación 08 — Consultas documentales por sucursal

Estado: **búsqueda y archivo conectados; duplicados todavía cerrados**.
Fecha: 2026-09-02.

## Alcance

Las rutas siguientes se incorporan al modo seguro:

- `GET /api/v1/documentos/buscar`;
- `GET /api/v1/documentos/archivo`.

Con ellas, 14 de las 59 rutas de negocio están conectadas al contexto verificado. Las otras 45 continúan fallando con `route_not_security_integrated`.

## Consulta mixta

Ambas respuestas combinan facturas cargadas y comprobantes internos. Por eso no basta con el permiso `documents.read`: el actor también debe superar `receipts.read`. Así se evita que una asignación exclusiva al módulo Documentos revele comprobantes de un módulo que no le fue concedido.

Los permisos de comprobantes internos pasan a ser sensibles a sucursal. Este criterio se aplicará también cuando se conecten sus rutas de alta, revisión y descarga.

## Límite de sucursal

- Un actor con sucursales limitadas debe seleccionar una sucursal autorizada.
- La búsqueda filtra por el `branch_id` verificado en las dos ramas de su consulta: facturas y comprobantes internos.
- El archivo aplica el mismo filtro a ambas fuentes.
- Si se solicita `sucursal_clave`, el handler resuelve su UUID dentro del data plane y vuelve a autorizar esa sucursal antes de consultar.
- Un director con alcance para todas las sucursales puede omitir la selección y consultar el tenant completo, pero nunca otro tenant.

La prueba de regresión crea documentos sintéticos en `DEMO-A` y `DEMO-B` y verifica que cada filtro devuelva exclusivamente el identificador de la sucursal solicitada.

## Duplicados pendientes

Las rutas de duplicados no se habilitan todavía. Los duplicados basados sólo en hash conservan archivo y factura original, pero el esquema anterior no registra de forma inequívoca la sucursal destino del archivo rechazado. Antes de exponer esa bandeja se añadirá la vinculación de sucursal y se definirán reglas para ocultar coincidencias que crucen sucursales sin revelar metadatos del documento original.
