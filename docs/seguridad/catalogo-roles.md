# Catálogo de roles

Estado: línea base funcional aprobada; todavía no implementada.
Fecha de aprobación: 2026-08-29.

## 1. Estructura

```text
Roles globales de la consultora
├── Director
├── Administrador de seguridad
├── Capturista
└── Soporte técnico

Roles internos del cliente
├── Responsable del cliente
├── Finanzas
└── Operador de sucursal

Identidades no humanas
└── Integración API
```

Los roles son plantillas funcionales. La autorización efectiva también depende del tenant, los módulos, las sucursales, las condiciones y la vigencia de la asignación.

## 2. Director de la consultora

Código: `CONSULTORA_DIRECTOR`.

Es la máxima autoridad funcional del producto.

Alcance:

- todos los clientes;
- todas las sucursales;
- todos los módulos; y
- reportes consolidados.

Puede:

- consultar y operar información financiera;
- supervisar capturistas;
- autorizar asignaciones;
- administrar clientes;
- generar reportes globales;
- consultar auditoría completa;
- suspender accesos; y
- modificar catálogos estructurales.

Condiciones:

- selecciona explícitamente el cliente;
- utiliza una llave física FIDO2 como autenticador principal;
- registra un segundo autenticador físico de respaldo;
- utiliza sesiones administrativas cortas;
- se reautentica para exportaciones y permisos globales; y
- cada operación conserva el tenant afectado.

No se permite una cuenta compartida de director.

## 3. Administrador de seguridad

Código: `CONSULTORA_SEGURIDAD`.

Administra identidades, autenticadores, sesiones y asignaciones, pero no el contenido financiero.

Puede:

- invitar y suspender usuarios;
- registrar o revocar autenticadores;
- asignar clientes, módulos y sucursales;
- revocar sesiones;
- ejecutar recuperaciones de cuenta;
- consultar auditoría y alertas; y
- configurar políticas de sesión.

No puede:

- consultar nóminas, recetas, ventas o ganancias;
- aprobar facturas;
- descargar reportes financieros;
- cambiar reglas contables; ni
- otorgarse a sí mismo el rol de director.

Puede consultar nombres de clientes y metadatos de usuarios porque son necesarios para administrar los accesos.

## 4. Capturista de la consultora

Código: `CONSULTORA_CAPTURISTA`.

Es el rol operativo principal.

Alcance:

- uno o varios clientes asignados;
- módulos específicos;
- todas o algunas sucursales; y
- vigencia opcional.

Puede, dentro de sus asignaciones:

- consultar la información completa;
- cargar y procesar documentos;
- revisar, corregir, aprobar y rechazar facturas;
- editar facturas aprobadas con motivo;
- capturar ventas;
- gestionar proveedores operativos;
- crear comprobantes;
- generar reportes PDF; y
- cancelar lotes y eliminar documentos no aprobados.

No puede:

- acceder a clientes no asignados;
- administrar usuarios;
- consultar auditoría global;
- cambiar políticas de seguridad;
- modificar reglas contables estructurales;
- exportar CSV masivo sin permiso adicional; ni
- aprobar un comprobante interno que creó personalmente.

Pertenecer a la consultora no concede acceso sin una asignación vigente.

## 5. Responsable del cliente

Código: `CLIENTE_RESPONSABLE`.

Representa al gerente o responsable dentro del grupo restaurantero.

Alcance:

- un único tenant; y
- todas o algunas sucursales de ese cliente.

Puede:

- consultar documentos, finanzas y reportes de su grupo;
- crear comprobantes internos;
- autorizar comprobantes ajenos;
- consultar actividad operativa de su cliente; y
- generar reportes PDF.

No puede:

- administrar usuarios;
- acceder a otros clientes;
- cambiar políticas globales;
- gestionar asignaciones de la consultora; ni
- generar consolidados entre clientes.

La consultora administra los usuarios del cliente.

## 6. Finanzas del cliente

Código: `CLIENTE_FINANZAS`.

Corresponde a contadores o personal financiero del grupo restaurantero.

Puede:

- consultar documentos aprobados;
- consultar ventas, gastos y Estado de Resultados;
- capturar y corregir ventas;
- consultar nómina y provisiones autorizadas;
- generar reportes PDF; y
- recibir un permiso condicionado de exportación.

No puede:

- aprobar facturas de la consultora;
- administrar usuarios;
- cambiar catálogos estructurales;
- acceder a otros clientes; ni
- consultar auditoría global.

## 7. Operador de sucursal

Código: `CLIENTE_OPERADOR`.

Es un rol operativo de alcance reducido.

Alcance:

- un cliente;
- una o varias sucursales específicas; y
- módulos expresamente asignados.

Puede:

- capturar ventas de su sucursal;
- crear comprobantes;
- consultar información operativa autorizada; y
- consultar el estado de sus propias capturas.

No puede:

- consultar resultados consolidados;
- consultar otras sucursales;
- exportar información masiva;
- aprobar sus propios comprobantes; ni
- administrar catálogos, usuarios o permisos.

## 8. Soporte técnico

Código: `SOPORTE_TECNICO`.

Puede permanentemente:

- consultar salud de los servicios;
- revisar errores técnicos;
- consultar metadatos enmascarados; y
- ejecutar diagnósticos sin contenido financiero.

El acceso a contenido está desactivado por defecto. Cuando resulte indispensable, debe ser temporal, limitado a un cliente y módulo, justificado, sujeto a expiración y completamente auditado.

Tener el rol de soporte no crea una membresía en ningún cliente.

## 9. Integración API

Código: `INTEGRACION_API`.

Es una identidad no humana para ERP, ventas, nómina u otros sistemas.

Características:

- pertenece exactamente a un tenant;
- sólo utiliza operaciones expresamente autorizadas;
- no inicia sesión en la interfaz;
- no comparte credenciales con personas;
- utiliza secretos o certificados rotables;
- puede suspenderse sin afectar usuarios humanos; y
- cada operación queda identificada con el nombre de la integración.

## 10. Composición de autorización

```text
Identidad
+ rol
+ tenant
+ módulos
+ sucursales
+ permisos condicionados
+ vigencia
= autorización efectiva
```

Ejemplo:

```text
Identidad: Laura Martínez
Rol: CONSULTORA_CAPTURISTA
Tenant: Grupo Los Arcos
Módulos: Documentos, proveedores y ventas
Sucursales: Centro y Norte
Exportación CSV: No
Vigencia: Indefinida
```

## 11. Reglas del catálogo

- las cuentas siempre son personales;
- un usuario puede tener más de un rol, pero cada asignación es explícita;
- los permisos se suman sin crear acceso global implícito;
- no existe herencia automática entre roles;
- sólo los roles de consultora pueden recibir varios clientes;
- los roles globales utilizan autenticación física reforzada;
- soporte e integraciones nunca reutilizan cuentas humanas; y
- no se crean inicialmente roles de supervisor, capturista sénior o auditor independiente.

Un rol nuevo sólo se añadirá cuando exista una necesidad operativa que no pueda expresarse mediante tenant, módulos, sucursales, acciones condicionadas o vigencia.
