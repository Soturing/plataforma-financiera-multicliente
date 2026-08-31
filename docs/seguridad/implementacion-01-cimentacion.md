# Implementación 01 — Cimentación de seguridad

Estado: **en construcción; primera entrega implementada y probada**.
Fecha: 2026-08-31.

## Objetivo de esta entrega

Convertir las decisiones aprobadas de tenant, identidad, sesión, módulo, sucursal y acción en estructuras ejecutables antes de conectar el control de acceso a los módulos financieros existentes.

## Implementado

- esquema PostgreSQL independiente para el plano de control;
- tenants, identidades, invitaciones, referencias de autenticadores, sesiones y asignaciones;
- módulos, sucursales y permisos condicionados por asignación;
- tokens de invitación y referencias de sesión almacenados sólo como resúmenes criptográficos;
- tabla de auditoría de seguridad separada y protegida contra `UPDATE` y `DELETE`;
- catálogo ejecutable de ocho roles y quince módulos;
- autorización de denegación predeterminada por acción, tenant, módulo y sucursal;
- comprobación de vigencia de identidad, sesión y asignación;
- prohibición de autoaprobación de comprobantes;
- exportaciones condicionadas y reautenticación para acciones C2 y C3;
- exigencia de llave física para acciones C3 de roles privilegiados;
- verificación OIDC de firma, algoritmo permitido, emisor, audiencia, expiración, emisión, `auth_time` y `sid`;
- carga de permisos vigentes desde el plano de control, sin confiar en roles contenidos en el token; y
- endpoint protegido `GET /api/v1/security/me` para consultar el contexto efectivo sin revelar tokens.

## Decisiones de implementación

La aplicación no implementa contraseñas ni WebAuthn directamente. Un proveedor de identidad maduro realizará el registro y autenticación con passkeys. El backend valida sus tokens OIDC firmados y vuelve a consultar el plano de control en cada petición, de modo que retirar una asignación no dependa de esperar a que expire un token.

El encabezado futuro `X-Tenant-Id` representa una selección solicitada, no una autoridad. Sólo se acepta después de compararlo con las asignaciones activas. La resolución del data plane utilizará el tenant ya autorizado.

## Evidencia automatizada

Las pruebas cubren:

- intento entre tenants;
- módulo no asignado;
- sucursal no asignada;
- administrador de seguridad intentando consultar finanzas;
- autoaprobación de comprobante;
- exportación sin permiso individual;
- director sin selección explícita de tenant;
- acción desconocida;
- asignación suspendida, revocada o expirada;
- sesión revocada;
- autenticación demasiado antigua;
- llave insuficiente para una acción C3;
- token con audiencia incorrecta o claims obligatorios ausentes;
- URLs OIDC inseguras;
- carga del contexto desde PostgreSQL; y
- rechazo de cambios a la auditoría.

## Aún bloqueado para producción

Esta entrega no convierte la demo actual en un sistema productivo. Permanecen pendientes:

1. elegir y configurar el proveedor de identidad con passkeys;
2. crear el procedimiento controlado del primer director;
3. implementar invitaciones, registro, recuperación, suspensión y revocación;
4. conectar todas las rutas financieras al contexto y permiso correspondientes;
5. eliminar los campos de actor enviados por el navegador;
6. implementar el router hacia un data plane independiente por tenant;
7. incorporar `tenant_id`, RLS y credenciales mínimas dentro de cada data plane;
8. escribir los eventos mediante un servicio de auditoría con encadenamiento criptográfico;
9. migrar archivos a almacenamiento separado por tenant; y
10. completar las pruebas end-to-end con dos data planes ficticios.

Hasta completar esos puntos, los endpoints de negocio existentes se consideran exclusivamente una demo local y no deben exponerse a Internet.
