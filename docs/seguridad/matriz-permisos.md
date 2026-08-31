# Matriz de permisos

Estado: línea base funcional aprobada; todavía no implementada.
Fecha de aprobación: 2026-08-29.

## 1. Alcance y principios

Esta matriz define quién puede ejecutar cada acción sobre la información de los grupos restauranteros administrados por la consultora.

Los nombres de los roles son funcionales y podrán ajustarse al aprobar el catálogo definitivo de roles. Un cambio de nombre no deberá ampliar permisos de manera implícita.

Reglas generales:

- toda autorización se valida en el servidor;
- se deniega por defecto lo que no aparezca permitido;
- el director tiene alcance sobre todos los clientes, pero selecciona un cliente explícitamente y cada acceso queda auditado;
- los capturistas operan únicamente en clientes, módulos y sucursales asignados;
- los empleados de un grupo restaurantero sólo acceden a su propio cliente;
- administrar identidades no concede acceso automático al contenido financiero;
- consultar no implica exportar, eliminar, aprobar ni administrar;
- ninguna persona puede modificar o eliminar la auditoría; y
- los permisos condicionados comienzan desactivados y requieren una asignación explícita.

## 2. Alcances utilizados

- **Todos:** todos los clientes, seleccionando uno explícitamente.
- **Asignados:** únicamente clientes, módulos y sucursales incluidos en una asignación vigente.
- **Propio:** exclusivamente el grupo restaurantero al que pertenece el usuario.
- **Sucursal asignada:** únicamente las sucursales incluidas en la membresía.
- **Condicionado:** permiso desactivado inicialmente, pero habilitable de forma explícita.
- **No:** operación denegada.

## 3. Documentos y facturas

| Acción | Director | Admin. seguridad | Capturista | Responsable cliente | Finanzas cliente | Operador |
|---|---|---|---|---|---|---|
| Consultar bandeja y archivo | Todos | No | Asignados | Propio | Propio | No |
| Abrir documento original | Todos | No | Asignados | Propio | Propio | No |
| Ver datos y expediente | Todos | No | Asignados | Propio | Propio | No |
| Cargar documentos | Todos | No | Asignados | No inicialmente | No | No |
| Realizar carga masiva | Todos | No | Asignados | No | No | No |
| Revisar y corregir pendientes | Todos | No | Asignados | No | No | No |
| Aprobar o rechazar factura | Todos | No | Asignados | No | No | No |
| Editar factura aprobada | Todos | No | Asignados | No | No | No |
| Cambiar si genera gasto | Todos | No | Asignados | No | No | No |
| Periodificar gasto | Todos | No | Asignados | No | No | No |
| Eliminar documento pendiente | Todos | No | Asignados | No | No | No |
| Eliminar documento aprobado | No mediante operación normal | No | No | No | No | No |
| Cancelar lote en proceso | Todos | No | Asignados | No | No | No |
| Eliminar lote cancelado | Todos | No | Asignados | No | No | No |
| Reprocesar o reclasificar lote | Todos | No | Asignados | No | No | No |
| Consultar duplicados | Todos | No | Asignados | No | No | No |
| Descartar duplicados | Todos | No | Asignados | No | No | No |

Condiciones:

- toda edición posterior a una aprobación exige motivo;
- los documentos aprobados no se eliminan desde la bandeja;
- eliminar pendientes, cancelar lotes y descartar duplicados deja auditoría;
- el capturista puede consultar todos los campos de sus asignaciones, conforme a la decisión D-008; y
- conocer un identificador o una dirección no concede acceso a un recurso fuera de la asignación.

## 4. Comprobantes internos

| Acción | Director | Admin. seguridad | Capturista | Responsable cliente | Finanzas cliente | Operador |
|---|---|---|---|---|---|---|
| Consultar comprobantes | Todos | No | Asignados | Propio | Propio | Propio asignado |
| Crear comprobante | Todos | No | Asignados | Propio | Condicionado | Propio asignado |
| Modificar antes de decisión | Todos | No | Asignados | Propio | Condicionado | Sólo el propio |
| Aprobar o rechazar | Todos | No | Asignados, excepto el propio | Propio, excepto el propio | Condicionado, excepto el propio | No |
| Descargar PDF o evidencia | Todos | No | Asignados | Propio | Propio | Propio asignado |
| Sustituir con CFDI | Todos | No | Asignados | Condicionado | Condicionado | No |

Una persona no puede aprobar el comprobante interno que ella misma creó. Se mantiene una sola aprobación realizada por una persona distinta del creador.

## 5. Proveedores y catálogos

| Acción | Director | Admin. seguridad | Capturista | Responsable cliente | Finanzas cliente | Operador |
|---|---|---|---|---|---|---|
| Consultar catálogos | Todos | No | Asignados | Propio | Propio | Propio |
| Crear o corregir proveedor | Todos | No | Asignados | No inicialmente | No | No |
| Registrar alias OCR | Todos | No | Asignados | No | No | No |
| Recordar clasificación | Todos | No | Asignados | No | No | No |
| Importar proveedores | Todos | No | Asignados | No | No | No |
| Activar o desactivar proveedor | Todos | No | Asignados | No | No | No |
| Crear subcategorías | Todos | No | No inicialmente | No | No | No |
| Crear centros de costo | Todos | No | No inicialmente | No | No | No |
| Modificar reglas contables estructurales | Todos | No | No | No | No | No |
| Consultar calidad y aprendizaje | Todos | No | Asignados | Condicionado | No | No |

Los capturistas conservan la administración operativa de proveedores y aprendizaje supervisado. Sólo el director modifica categorías, centros de costo y reglas contables estructurales.

## 6. Ventas y provisiones

| Acción | Director | Admin. seguridad | Capturista | Responsable cliente | Finanzas cliente | Operador |
|---|---|---|---|---|---|---|
| Consultar ventas | Todos | No | Asignados | Propio | Propio | Sucursal asignada |
| Capturar ventas manuales | Todos | No | Asignados | Condicionado | Propio | Sucursal asignada |
| Importar imagen o archivo | Todos | No | Asignados | Condicionado | Propio | Sucursal asignada |
| Corregir ventas | Todos | No | Asignados | Condicionado | Propio | Sólo periodo abierto |
| Corregir periodos cerrados | Todos | No | Condicionado | No | Condicionado | No |
| Modificar provisiones fijas | Todos | No | No inicialmente | No | Condicionado | No |
| Registrar cierre real de provisión | Todos | No | Asignados | Condicionado | Propio | No |

## 7. Finanzas, Analytics y reportes

| Acción | Director | Admin. seguridad | Capturista | Responsable cliente | Finanzas cliente | Operador |
|---|---|---|---|---|---|---|
| Consultar Analytics | Todos | No | Asignados | Propio | Propio | Sucursal asignada |
| Consultar Estado de Resultados | Todos | No | Asignados | Propio | Propio | Sucursal asignada |
| Consultar nómina y gastos fijos | Todos | No | Asignados | Propio | Propio | Condicionado |
| Generar reporte PDF | Todos | No | Asignados | Propio | Propio | Condicionado |
| Descargar CSV masivo | Todos | No | Condicionado | Condicionado | Condicionado | No |
| Reporte consolidado entre clientes | Todos | No | No | No | No | No |
| Comparar clientes diferentes | Todos | No | No | No | No | No |

Los capturistas pueden generar los reportes PDF de sus asignaciones. La exportación CSV masiva comienza desactivada y sólo se habilita mediante un permiso individual explícito.

## 8. Usuarios y seguridad

| Acción | Director | Admin. seguridad | Capturista | Responsable cliente | Finanzas cliente | Operador |
|---|---|---|---|---|---|---|
| Crear cliente | Sí | Sí | No | No | No | No |
| Configurar sucursales | Sí | Ejecutar configuración autorizada | No | No | No | No |
| Invitar usuario | Sí | Sí | No | No | No | No |
| Asignar capturista a clientes | Sí | Sí | No | No | No | No |
| Asignar módulos y sucursales | Sí | Sí | No | No | No | No |
| Otorgar acceso global | Sí | Ejecutar con autorización del director | No | No | No | No |
| Suspender usuario | Sí | Sí | No | No | No | No |
| Revocar sesiones | Sí | Sí | Sólo la propia | Sólo la propia | Sólo la propia | Sólo la propia |
| Restablecer acceso | Sí | Sí | No | No | No | No |
| Modificar políticas del sistema | Sí | No inicialmente | No | No | No | No |

El administrador de seguridad ejecuta la gestión de identidades y accesos, pero no decide reglas financieras ni obtiene acceso al contenido financiero por esa función.

## 9. Auditoría

| Acción | Director | Admin. seguridad | Capturista | Responsable cliente | Finanzas cliente | Operador |
|---|---|---|---|---|---|---|
| Consultar auditoría global | Sí | Sí | No | No | No | No |
| Consultar auditoría del cliente | Sí | Sí | Operación asignada | Propio, sólo lectura | No | No |
| Consultar actividad propia | Sí | Sí | Sí | Sí | Sí | Sí |
| Exportar auditoría | Sí | Condicionado | No | No | No | No |
| Modificar o eliminar auditoría | No | No | No | No | No | No |
| Consultar alertas de seguridad | Sí | Sí | No | No | No | No |
| Cerrar una alerta | Sí | Sí | No | No | No | No |

## 10. Soporte técnico e integraciones

- soporte técnico no tiene acceso permanente al contenido de clientes;
- puede consultar salud, errores técnicos y metadatos enmascarados;
- el acceso temporal a contenido requiere justificación, cliente, módulos, acciones y expiración;
- las integraciones utilizan identidades técnicas independientes;
- cada integración se limita a un tenant y a acciones concretas;
- una identidad técnica no puede iniciar sesión en la interfaz; y
- las credenciales de una persona nunca se comparten con una integración.

## 11. Reglas que deberán convertirse en pruebas

- una identidad del cliente A no puede consultar ni modificar recursos del cliente B;
- un capturista no puede operar fuera de sus asignaciones vigentes;
- un cambio de asignación revoca las sesiones afectadas;
- un administrador de seguridad no puede consultar contenido financiero;
- una persona no puede aprobar su propio comprobante interno;
- un capturista sin permiso de exportación no puede descargar el CSV;
- un documento aprobado no puede eliminarse mediante la operación ordinaria;
- ningún rol puede modificar o eliminar la auditoría; y
- el acceso global del director siempre conserva el cliente consultado en la bitácora.
