# Acciones sensibles

Estado: línea base funcional aprobada; todavía no implementada.
Fecha de aprobación: 2026-08-29.

## 1. Principio

Tener permiso para un módulo no elimina los controles adicionales de sus acciones sensibles. La autorización de una acción combina rol, tenant, módulo, sucursal, estado del recurso, nivel de autenticación y condiciones de riesgo.

## 2. Niveles de control

### C0 — Operación ordinaria

Requiere:

- sesión válida;
- tenant y alcance autorizados;
- validación en servidor; y
- auditoría operativa normal.

### C1 — Acción controlada

Añade:

- auditoría detallada;
- identificación del recurso;
- límites de frecuencia o volumen; y
- detección de comportamiento anormal.

No exige reautenticación en cada uso porque incluye actividades frecuentes.

### C2 — Acción sensible

Añade:

- confirmación explícita;
- motivo cuando corresponda;
- autenticación reciente, inicialmente no mayor a 15 minutos;
- conservación de la versión anterior; y
- auditoría reforzada.

### C3 — Acción crítica

Añade:

- reautenticación inmediata mediante passkey o llave física;
- tenant y alcance claramente visibles;
- motivo obligatorio;
- auditoría reforzada;
- notificación al usuario o responsable afectado; y
- alerta ante comportamiento inusual.

La primera versión no exige doble aprobación.

## 3. Catálogo de acciones sensibles

| ID | Acción | Nivel | Control especial |
|---|---|---:|---|
| AS-01 | Consultar nómina detallada, recetas o información financiera restringida | C1 | Registrar usuario, tenant, módulo y alcance |
| AS-02 | Abrir o descargar un documento original | C1 | Enlace breve, individual y no reutilizable |
| AS-03 | Generar un reporte PDF | C1 | Marca de agua con usuario, cliente y fecha |
| AS-04 | Aprobar o rechazar una factura | C1 | Decisión inmutable y actor derivado de sesión |
| AS-05 | Editar una factura ya aprobada | C2 | Motivo, versión anterior y actualización auditable |
| AS-06 | Cambiar si una factura genera gasto | C2 | Motivo y recálculo transaccional de Analytics |
| AS-07 | Corregir ventas de un periodo cerrado | C2 | Motivo, valores anteriores y periodo afectado |
| AS-08 | Aprobar o rechazar comprobante interno | C2 | El creador no puede aprobarlo |
| AS-09 | Eliminar documentos no aprobados | C2 | Confirmación y evidencia mínima conservada |
| AS-10 | Cancelar o eliminar un lote | C2 | Mostrar cantidad de documentos afectados |
| AS-11 | Ejecutar una importación masiva | C2 | Vista previa y tenant inmutable durante el proceso |
| AS-12 | Cambiar catálogos contables estructurales | C2 | Director, motivo y versión anterior |
| AS-13 | Modificar provisiones o nómina agregada | C2 | Periodo, sucursales y efecto financiero visibles |
| AS-14 | Suspender un usuario o revocar sus sesiones | C2 | Notificación al afectado y motivo |
| AS-15 | Descargar CSV o exportación masiva | C3 | Permiso individual, reautenticación y límites |
| AS-16 | Generar reporte consolidado entre clientes | C3 | Sólo director y selección explícita de clientes |
| AS-17 | Asignar un rol global | C3 | El administrador no puede otorgárselo a sí mismo |
| AS-18 | Recuperar una cuenta privilegiada | C3 | Revocar sesiones y autenticadores anteriores |
| AS-19 | Crear o revelar credencial de integración | C3 | Mostrar el secreto una sola vez y registrar rotación |
| AS-20 | Dar acceso temporal de soporte a contenido | C3 | Tenant, módulos, motivo y expiración obligatorios |
| AS-21 | Suspender o reactivar un cliente | C3 | Mostrar impacto y conservar los datos |
| AS-22 | Exportar auditoría | C3 | Alcance, periodo y motivo obligatorios |
| AS-23 | Cambiar políticas globales de seguridad | C3 | Sólo director y registro de valores anteriores |
| AS-24 | Iniciar la baja definitiva de un tenant | C3 | Periodo de retención; no eliminar inmediatamente |
| AS-25 | Rotar claves o certificados de integración | C3 | Revocar material anterior y verificar funcionamiento |

## 4. Acciones prohibidas

No se habilitan mediante roles ordinarios:

- eliminar facturas aprobadas desde la bandeja;
- eliminar o modificar auditoría;
- aprobar un comprobante propio;
- otorgarse a uno mismo un rol global;
- acceder directamente a otro tenant;
- dar acceso permanente a soporte sobre contenido;
- compartir cuentas o autenticadores;
- utilizar una integración para iniciar sesión en la interfaz;
- eliminar definitivamente un cliente de forma inmediata; y
- desactivar controles de tenant o auditoría.

La eliminación definitiva de datos de un cliente forma parte de un procedimiento separado de baja, posterior al periodo de retención y con evidencia preservada.

## 5. Exportaciones

### 5.1 Reportes PDF

Los capturistas pueden generar reportes de sus asignaciones. Cada PDF incluirá:

- marca de agua visible;
- usuario generador;
- cliente;
- fecha y hora;
- identificador único; y
- registro de bloques y periodo incluidos.

### 5.2 CSV y exportación masiva

Comienza desactivada y requiere:

- permiso individual;
- reautenticación;
- límite de registros;
- filtros visibles antes de descargar;
- archivo cifrado temporalmente;
- enlace de corta duración; y
- alerta ante un volumen anormal.

### 5.3 Reportes entre clientes

Son exclusivos del director y requieren:

- selección explícita de clientes;
- exclusión de datos personales de nómina;
- preferencia por información agregada;
- reautenticación para cada generación; y
- registro de clientes, periodo y métricas consultadas.

## 6. Compatibilidad futura

Aunque la primera versión no exige doble aprobación, cada política crítica conserva el atributo:

```text
requiere_aprobacion_adicional = false
```

Podrá activarse posteriormente por cliente, acción o nivel de riesgo sin rediseñar el modelo.
