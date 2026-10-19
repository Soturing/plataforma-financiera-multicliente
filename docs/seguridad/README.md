# Diseño de seguridad

Estado general: dirección aprobada; todavía no implementada.
Última actualización: 2026-08-30.

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

## Construcción

- [Plan de implementación](plan-implementacion.md) — aprobado (D-018 a D-026).
- [Fase 1 — Proveedor de identidad](fase1-identidad.md) — prueba técnica completada en local.
- [Fases 2 a 4 — Plano de control, sesiones y autorización](fases2-4-acceso.md) — visible en el 8010; incluye la guía de revisión.
- [Fase 5 — Data plane por cliente y RLS](fase5-data-plane.md) — `GRUPO-DEMO` en su propio stack; segundo cliente ficticio para pruebas.
- [Fase 6 — Ciclo de vida](fase6-ciclo-vida.md) — asignaciones, dispositivos, recuperación, baja, reingreso e inactividad.
- [Fase 7 — Secretos, claves y respaldos](fase7-secretos-respaldos.md) — OpenBao, claves por cliente, respaldos cifrados y restauración de prueba.
- [Despliegue en servidor](despliegue-servidor.md) — contenedores por cliente, gocryptfs, proxy, recomendación de VPS y bucket, guía paso a paso.

## Regla de implementación

La construcción debe mantener estas decisiones como criterios verificables. Si durante el desarrollo se necesita modificar una decisión, el cambio se documenta antes de alterar el comportamiento correspondiente.

Ninguna amenaza con riesgo inicial de 12 o más puede pasar a producción sin controles, detección, respuesta, pruebas y riesgo residual documentado.
