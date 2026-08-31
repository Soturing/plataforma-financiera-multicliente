# Hoja de ruta del producto

Estado general: **pendiente; estos puntos todavía no están implementados**.

Este documento registra los siguientes frentes de producto para las próximas etapas. Las decisiones de arquitectura deberán resolverse antes de desarrollar cada uno.

## 1. Usuarios y acceso con alta seguridad

Objetivo: identificar a cada persona, limitarla a los restaurantes y funciones que le correspondan y mantener trazabilidad de sus acciones.

- Priorizar un método sin contraseña basado en **passkeys/WebAuthn**; evaluar SSO empresarial cuando aplique.
- No construir un sistema criptográfico propio: integrar un proveedor de identidad maduro y auditable.
- Definir roles y permisos con mínimo privilegio, aislamiento por restaurante y sesiones de corta duración con revocación.
- Diseñar recuperación de cuenta segura, protección contra abuso, límites de intentos y alertas de acceso anómalo.
- Registrar inicios de sesión, cambios de permisos y acciones sensibles en una bitácora inmutable.
- Preparar manejo seguro de secretos, respaldos, pruebas de penetración y respuesta a incidentes antes de producción.

La elección definitiva entre passkeys, SSO u otro mecanismo queda pendiente de conocer dispositivos, cantidad de usuarios y necesidades de recuperación del cliente.

## 2. Bloqueo por falta de pago

Objetivo: habilitar el servicio únicamente para clientes con una suscripción o contrato vigente.

- Mantener el estado de servicio por cliente, no por usuario individual, y validarlo en el servidor.
- Integrar una fuente confiable de facturación con eventos firmados e idempotentes.
- Definir avisos previos, fecha de vencimiento, periodo de gracia y responsables autorizados para reactivar el servicio.
- Al suspender, conservar los datos y preferir un modo limitado o de solo lectura antes de impedir toda recuperación de información.
- Evitar que una manipulación del navegador permita saltarse el bloqueo; cada operación protegida debe validar la vigencia en el backend.
- Registrar suspensiones, reactivaciones y excepciones administrativas en auditoría.

## 3. Cambio de reportes

Objetivo: sustituir los reportes actuales cuando se reciba la nueva dirección funcional.

- Mantener la implementación vigente hasta contar con la definición nueva.
- Documentar para cada reporte audiencia, periodo, filtros, indicadores, comparaciones, formato de salida y reglas de cálculo.
- Validar los nuevos resultados contra ejemplos aprobados antes de retirar los formatos anteriores.

Este punto queda a la espera de las instrucciones y referencias del usuario.

## 4. Sistema reutilizable para distintos restaurantes

Objetivo: convertir la solución actual en un producto configurable y aislado para varios clientes, sin copiar manualmente el código.

- Sustituir nombres, logotipos, colores, sucursales, direcciones y textos de Restaurante Demo Uno por configuración de marca por cliente.
- Incorporar una entidad de cliente o `tenant` y aislar sus usuarios, documentos, catálogos, reportes, archivos y auditoría.
- Exigir el contexto del cliente en el backend y en la base de datos; no depender solamente de filtros visuales.
- Crear una plantilla de alta que permita registrar una nueva marca sin modificar el código fuente.
- Separar secretos, almacenamiento, integraciones y políticas de retención por cliente.
- Añadir pruebas automáticas que detecten fuga de datos o de identidad visual entre restaurantes.

Este frente deberá coordinarse desde el inicio con usuarios, permisos y control de suscripción, porque los tres dependen del mismo modelo de cliente.
