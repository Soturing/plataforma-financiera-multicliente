# Implementación 08 — Consultas documentales por sucursal

Estado: **búsqueda y archivo conectados; duplicados conectados posteriormente en la implementación 09**.
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

## Evolución posterior

El esquema anterior no registraba de forma inequívoca la sucursal destino de un archivo rechazado por hash. La implementación 09 añadió esa vinculación y las reglas que ocultan coincidencias entre sucursales sin revelar metadatos del documento original.
