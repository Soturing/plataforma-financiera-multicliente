# Auditoría y alertas

Estado: línea base funcional aprobada; todavía no implementada.
Fecha de aprobación: 2026-08-29.

## 1. Separación de registros

```text
Auditoría inmutable
├── Quién hizo qué, sobre qué cliente y con qué resultado
│
Historial de versiones
├── Cómo cambió cada registro de negocio
│
Logs técnicos
└── Errores, rendimiento y diagnóstico sin contenido sensible
```

La auditoría no debe convertirse en una segunda base de datos con copias de toda la información protegida.

## 2. Datos obligatorios de cada evento

Cada evento auditable incluye:

- identificador único;
- fecha y hora UTC;
- tipo de evento;
- resultado: éxito, rechazo o error;
- identidad real del actor;
- tipo de actor: persona, integración o sistema;
- rol efectivo;
- tenant;
- módulo;
- sucursal, cuando aplique;
- acción;
- tipo e identificador del recurso;
- sesión;
- método y nivel de autenticación;
- dirección de red y dispositivo, con acceso restringido;
- motivo, cuando sea obligatorio;
- identificador de petición;
- identificador de operación correlacionada;
- cantidad de registros o bytes afectados;
- nivel de sensibilidad; y
- política de autorización aplicada.

El actor siempre se obtiene de la sesión. Los campos enviados por el cliente, como `revisada_por`, no son fuente de identidad.

## 3. Información prohibida en logs

No se almacenan en logs:

- contraseñas;
- claves privadas de passkeys;
- tokens de sesión;
- secretos de integración;
- códigos de recuperación;
- contenido completo de facturas;
- archivos;
- recetas completas;
- listados completos de nómina;
- cuerpos completos de peticiones;
- números bancarios completos;
- fotografías o documentos personales; ni
- datos introducidos en formularios de autenticación.

Para cambios financieros, la auditoría registra:

```text
campos_modificados
version_anterior_id
version_nueva_id
```

Los valores exactos anteriores permanecen cifrados en el historial de versiones del tenant, no en una bitácora global.

## 4. Eventos obligatorios

### 4.1 Identidad

- invitación y activación;
- inicio de sesión exitoso o fallido;
- cierre de sesión;
- registro o eliminación de passkey;
- registro de llave física;
- recuperación de cuenta;
- suspensión;
- revocación de sesiones;
- cambio de dispositivo; y
- cambio de correo o identidad.

### 4.2 Autorización

- creación, cambio o eliminación de membresía;
- asignación o revocación de rol;
- cambio de módulos o sucursales;
- habilitación de exportación;
- otorgamiento de acceso global;
- acceso denegado;
- intento entre tenants; y
- cambio de política.

### 4.3 Operaciones de negocio

- carga de documentos;
- apertura o descarga de originales;
- aprobación, corrección y rechazo;
- edición posterior a aprobación;
- eliminación de pendientes;
- cancelación de lotes;
- importación masiva;
- creación y aprobación de comprobantes;
- cambios de proveedores;
- cambios contables estructurales;
- captura y corrección de ventas;
- modificación de provisiones; y
- consulta de nómina detallada o recetas.

### 4.4 Exportaciones

- generación y descarga de PDF;
- exportación CSV;
- cantidad de registros;
- filtros utilizados;
- clientes y periodos incluidos;
- caducidad del archivo; y
- descarga exitosa o fallida.

### 4.5 Administración

- alta, suspensión y reactivación de tenant;
- alta y cambio de sucursales;
- cambios de retención;
- alta y rotación de integraciones;
- accesos temporales de soporte;
- restauraciones de respaldo; y
- cambios de claves o certificados.

### 4.6 Sistema de auditoría

- retrasos o fallos de recepción;
- eventos fuera de secuencia;
- intentos de modificación;
- verificación de integridad;
- aplicación de políticas de retención; y
- restauración de evidencia.

## 5. Retención inicial

Estos periodos son una política inicial de producto y deben validarse contractualmente y con asesoría legal antes de producción.

| Información | Retención inicial |
|---|---:|
| Cambios financieros y administrativos | 7 años |
| Roles, permisos y ciclo de vida de usuarios | 7 años |
| Exportaciones y reportes generados | 7 años de metadatos |
| Accesos temporales de soporte | 7 años |
| Alertas e incidentes | 7 años |
| Consultas a datos restringidos | 2 años |
| Aperturas y descargas de documentos | 2 años |
| Logs de peticiones técnicas | 90 días |
| Logs detallados de depuración | 30 días |
| Archivo temporal de exportación | Máximo 24 horas |
| Métricas técnicas sin identidad | 2 años |

Al finalizar la retención, la eliminación es automática, controlada y genera un evento de auditoría.

## 6. Protección de la bitácora

- almacenamiento de sólo anexado;
- credenciales distintas de las utilizadas por la aplicación;
- ningún rol de aplicación puede ejecutar `UPDATE` o `DELETE`;
- copia periódica en almacenamiento inmutable;
- encadenamiento criptográfico de eventos;
- resumen firmado diariamente;
- detección de huecos en la secuencia;
- copias cifradas;
- prueba trimestral de restauración;
- relojes sincronizados y timestamps en UTC; y
- alertas cuando la auditoría deja de recibir eventos.

Una operación sensible no se considera completada si no puede producir su evento obligatorio.

## 7. Alertas inmediatas

Generan alerta sin esperar un umbral:

- intento de acceso entre tenants;
- asignación de rol global;
- recuperación de cuenta privilegiada;
- administrador de seguridad intentando acceder a finanzas;
- acceso temporal de soporte a contenido;
- creación o revelación de credencial de integración;
- suspensión o reactivación de tenant;
- intento de alterar auditoría;
- interrupción del flujo de auditoría;
- exportación masiva fuera del patrón habitual;
- nuevo autenticador seguido de exportación o cambio de permisos; y
- uso de una sesión revocada.

## 8. Umbrales iniciales

Se ajustan después del piloto.

| Comportamiento | Respuesta inicial |
|---|---|
| 5 fallos de autenticación en 10 minutos | Limitar nuevos intentos |
| 10 fallos en 30 minutos | Alertar a seguridad |
| Más de 20 documentos originales en 10 minutos | Alertar y evaluar suspensión |
| Más de 200 registros restringidos en 10 minutos | Alertar |
| Más de 10 PDF en 15 minutos | Alertar |
| Más de una exportación CSV por hora | Alertar |
| CSV con más de 10,000 registros | Confirmación adicional y alerta |
| Más de 10 cambios de tenant en 10 minutos | Alertar |
| Operación crítica desde dispositivo nuevo | Reautenticar y alertar |
| Passkey nueva seguida de acción C3 en 24 horas | Alertar |

Los umbrales no sustituyen el análisis de comportamiento. Un solo acceso puede resultar grave aunque no alcance un límite numérico.

## 9. Acceso a la auditoría

- el director consulta auditoría global y por cliente;
- el administrador de seguridad consulta seguridad, identidad y metadatos globales;
- el capturista consulta actividad propia e historial operativo de sus asignaciones;
- el responsable del cliente consulta actividad de su tenant en modo de sólo lectura;
- Finanzas y Operador consultan actividad propia;
- Soporte consulta eventos técnicos enmascarados; y
- las integraciones no consultan auditoría mediante su identidad técnica.

Exportar auditoría es una acción C3 independiente del permiso de consulta.

## 10. Informes de seguridad

- alertas críticas: inmediatas;
- resumen diario: administrador de seguridad;
- resumen semanal: director;
- revisión mensual: usuarios, asignaciones, exportaciones y cuentas inactivas;
- revisión trimestral: integridad, restauración, retención e integraciones; y
- revisión posterior a cada incidente.
