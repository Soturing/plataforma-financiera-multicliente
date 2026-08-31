# Catálogo de módulos

Estado: línea base funcional aprobada; todavía no implementada.
Fecha de aprobación: 2026-08-29.

## 1. Principio

Un módulo es una frontera de autorización, no necesariamente una pantalla. Una interfaz puede reunir información de varios módulos, pero sólo mostrará aquello para lo que la identidad tenga una asignación vigente.

Los módulos se combinan con rol, tenant, sucursales, acciones, condiciones y vigencia. Tener acceso a un módulo no concede automáticamente todas sus acciones.

## 2. Módulos de negocio actuales

### 2.1 Documentos y facturas

Código: `DOCUMENTOS`.

Incluye:

- carga individual y masiva;
- archivos originales;
- OCR e interpretación;
- clasificación documental;
- bandeja de revisión;
- aprobación, corrección y rechazo;
- edición posterior;
- lotes;
- duplicados;
- archivo documental; y
- periodificación de facturas.

OCR e IA son etapas internas del flujo documental y no módulos independientes.

### 2.2 Comprobantes internos

Código: `COMPROBANTES_INTERNOS`.

Incluye:

- creación;
- evidencia;
- consulta;
- aprobación y rechazo;
- generación de PDF; y
- sustitución posterior por CFDI.

Permanece separado de Documentos porque aplica la regla que impide aprobar el comprobante propio.

### 2.3 Proveedores

Código: `PROVEEDORES`.

Incluye:

- directorio y contactos;
- altas y correcciones;
- RFC;
- proveedores informales;
- alias OCR;
- importación masiva;
- activación y desactivación; y
- aprendizaje de clasificación por proveedor.

No incluye categorías ni centros de costo estructurales.

### 2.4 Catálogos contables

Código: `CATALOGOS_CONTABLES`.

Incluye:

- categorías;
- subcategorías;
- centros de costo;
- reglas contables estructurales;
- reglas de periodificación; y
- parámetros financieros generales.

Separarlo de Proveedores evita que una corrección operativa permita cambiar toda la estructura financiera.

### 2.5 Ventas

Código: `VENTAS`.

Incluye:

- captura diaria;
- métodos de pago;
- desglose comercial;
- visitas;
- importación desde imágenes o archivos;
- correcciones;
- conciliación; e
- integración futura con WANSOFT.

Su alcance normalmente se limita por sucursal.

### 2.6 Finanzas y análisis

Código: `FINANZAS`.

Incluye:

- Analytics;
- gastos;
- Estado de Resultados;
- punto de equilibrio;
- utilidad;
- comparaciones semanales y mensuales;
- provisiones de gastos fijos;
- cierres de provisiones; e
- indicadores por sucursal.

Puede mostrar el total agregado de nómina como parte del Estado de Resultados, pero no el detalle de empleados.

### 2.7 Reportes

Código: `REPORTES`.

Incluye:

- vista previa;
- reportes financieros semanales;
- reportes mensuales;
- comparativos;
- PDF de compras;
- reporte ejecutivo; y
- consolidado entre clientes.

El acceso al módulo permite preparar y consultar reportes. Descargar, exportar masivamente o consolidar entre clientes son acciones independientes.

## 3. Información sensible o prevista

### 3.1 Nómina

Código: `NOMINA`.

Incluye, cuando se incorpore:

- empleados;
- salarios individuales;
- prestaciones;
- datos fiscales y laborales;
- incidencias;
- archivos de dispersión;
- recibos de nómina; e
- historial individual.

Una identidad puede ver el gasto agregado de nómina en Finanzas sin acceder al salario de cada empleado.

Estado actual: parcial; sólo existen importes agregados dentro de provisiones financieras.

### 3.2 Inventarios

Código: `INVENTARIOS`.

Incluirá:

- existencias;
- entradas y salidas;
- costos;
- mermas;
- transferencias;
- conteos;
- ajustes; e
- historial por sucursal.

Estado actual: previsto, no implementado.

### 3.3 Recetas

Código: `RECETAS`.

Incluirá:

- ingredientes;
- cantidades;
- rendimientos;
- costos teóricos;
- versiones;
- preparaciones; y
- relación con inventarios.

Permanece independiente por tratarse de propiedad intelectual especialmente sensible.

Estado actual: previsto, no implementado.

## 4. Módulos administrativos

### 4.1 Clientes y sucursales

Código: `ADMIN_CLIENTES`.

Incluye:

- alta y suspensión de tenants;
- restaurantes, marcas y sucursales;
- configuración visual;
- estado del servicio;
- retención contractual;
- provisionamiento y baja; y
- configuración regional.

No incluye usuarios ni permisos.

### 4.2 Identidades y accesos

Código: `IDENTIDADES_ACCESOS`.

Incluye:

- invitaciones;
- roles;
- membresías;
- asignaciones;
- passkeys y llaves;
- sesiones;
- recuperaciones;
- suspensiones; y
- revocaciones.

Este módulo no concede acceso al contenido de otros módulos.

### 4.3 Auditoría y seguridad

Código: `AUDITORIA_SEGURIDAD`.

Incluye:

- inicios de sesión;
- cambios de permisos;
- acciones sensibles;
- actividad por tenant;
- alertas;
- investigaciones;
- evidencia preservada; y
- respuesta a incidentes.

La bitácora no puede modificarse desde este módulo.

### 4.4 Integraciones

Código: `INTEGRACIONES`.

Incluye:

- identidades técnicas;
- credenciales o certificados;
- alcances de API;
- webhooks;
- rotación;
- suspensión; y
- estado y errores de sincronización.

Cada integración pertenece exactamente a un tenant.

### 4.5 Operación técnica

Código: `OPERACION_TECNICA`.

Incluye:

- salud de servicios;
- colas;
- errores técnicos;
- métricas de procesamiento;
- capacidad y almacenamiento; y
- diagnóstico con datos enmascarados.

Está dirigido a soporte y administradores técnicos. No concede acceso automático a documentos o finanzas.

## 5. Elementos que no son módulos

- las sucursales son alcances dentro de los módulos;
- exportar y aprobar son acciones;
- OCR e IA son capacidades internas de Documentos;
- el inicio reúne datos de módulos ya autorizados;
- el tenant es la frontera del cliente;
- las passkeys son mecanismos de autenticación; y
- el soporte temporal es una asignación excepcional.

## 6. Ejemplo de asignación

```text
Usuario: Capturista 04
Rol: CONSULTORA_CAPTURISTA
Tenant: Grupo A
Módulos:
  - DOCUMENTOS
  - COMPROBANTES_INTERNOS
  - PROVEEDORES
  - VENTAS
  - FINANZAS
  - REPORTES
Sucursales:
  - Centro
  - Norte
No autorizado:
  - NOMINA
  - RECETAS
  - IDENTIDADES_ACCESOS
  - AUDITORIA_SEGURIDAD
Exportación CSV:
  - Desactivada
```
