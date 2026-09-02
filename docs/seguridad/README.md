# Diseño de seguridad

Estado general: dirección aprobada; implementación en curso.
Última actualización: 2026-09-02.

Esta carpeta conserva las ocho definiciones aprobadas antes de iniciar la construcción del sistema de usuarios, roles y aislamiento multi-tenant.

## Documentos aprobados

1. [Matriz de permisos](matriz-permisos.md)
2. [Registro de amenazas](registro-amenazas.md)
3. [Catálogo de roles](catalogo-roles.md)
4. [Catálogo de módulos](catalogo-modulos.md)
5. [Acciones sensibles](acciones-sensibles.md)
6. [Auditoría y alertas](auditoria-alertas.md)
7. [Ciclo de vida de usuarios](ciclo-vida-usuarios.md)
8. [Arquitectura de aislamiento multi-tenant](arquitectura-aislamiento.md)
9. [Política de repositorio y control de versiones](politica-repositorio.md)

## Avance de construcción

- [Implementación 01 — Cimentación de seguridad](implementacion-01-cimentacion.md)
- [Implementación 02 — Ciclo inicial de identidades](implementacion-02-ciclo-identidades.md)
- [Implementación 03 — Router seguro de data planes](implementacion-03-router-data-plane.md)
- [Implementación 04 — RLS y roles mínimos del data plane](implementacion-04-rls-credenciales.md)
- [Implementación 05 — Catálogo cerrado de rutas de negocio](implementacion-05-catalogo-rutas.md)
- [Implementación 06 — Primer flujo vertical seguro de facturas](implementacion-06-flujo-facturas.md)
- [Implementación 07 — Dependencias que procesan entradas no confiables](implementacion-07-dependencias.md)
- [Implementación 08 — Consultas documentales por sucursal](implementacion-08-consultas-documentales.md)

## Regla de implementación

La construcción debe mantener estas decisiones como criterios verificables. Si durante el desarrollo se necesita modificar una decisión, el cambio se documenta antes de alterar el comportamiento correspondiente.

Ninguna amenaza con riesgo inicial de 12 o más puede pasar a producción sin controles, detección, respuesta, pruebas y riesgo residual documentado.
