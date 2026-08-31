# Registro de amenazas

Estado: registro inicial aprobado; todavía no implementado.
Fecha de aprobación: 2026-08-29.

## 1. Objetivo

Este registro identifica escenarios capaces de comprometer la confidencialidad, integridad, disponibilidad o separación entre los grupos restauranteros administrados por la consultora.

El registro deberá actualizarse durante el diseño, desarrollo, pruebas, operación e investigación de incidentes. La ausencia de una amenaza en este documento no implica su aceptación automática.

## 2. Evaluación

El riesgo inicial se calcula antes de aplicar controles:

```text
Riesgo inicial = impacto × probabilidad
```

Impacto:

- **1 — Bajo:** inconveniente limitado y recuperable.
- **2 — Medio:** afecta una operación o un conjunto reducido de información.
- **3 — Alto:** afecta información confidencial u operaciones relevantes.
- **4 — Crítico:** expone información financiera, personal, propiedad intelectual, control administrativo o múltiples clientes.

Probabilidad:

- **1 — Improbable:** requiere condiciones excepcionales.
- **2 — Posible:** requiere acceso o condiciones específicas.
- **3 — Probable:** puede producirse mediante errores comunes, abuso interno o una cuenta comprometida.
- **4 — Muy probable:** ya existe una ruta directa o el control todavía no está implementado.

Tratamiento:

- **12–16:** bloquea producción hasta contar con controles y pruebas satisfactorias.
- **8–11:** requiere tratamiento antes del lanzamiento.
- **4–7:** debe planificarse y vigilarse.
- **1–3:** puede aceptarse temporalmente con seguimiento documentado.

## 3. Registro inicial

| ID | Amenaza | I | P | Riesgo | Tratamiento principal |
|---|---|---:|---:|---:|---|
| AM-01 | Usuario del cliente A accede a registros del cliente B | 4 | 4 | 16 | Tenant obligatorio, base aislada y pruebas cruzadas |
| AM-02 | Un endpoint acepta acciones sin autenticación real | 4 | 4 | 16 | Proveedor de identidad, passkeys y sesión validada en servidor |
| AM-03 | Un usuario suplanta a otro enviando campos como `revisada_por` | 4 | 4 | 16 | Actor derivado exclusivamente de la sesión |
| AM-04 | Una consulta omite el filtro o contexto del cliente | 4 | 4 | 16 | Enrutamiento obligatorio por tenant y aislamiento de datos |
| AM-05 | La cuenta del director es comprometida | 4 | 3 | 12 | Llave FIDO2, sesión corta, reautenticación y alertas |
| AM-06 | La recuperación de cuenta permite ingeniería social | 4 | 3 | 12 | Segundo autenticador, espera, verificación y notificaciones |
| AM-07 | Un capturista recibe por error acceso a otro cliente | 4 | 3 | 12 | Resumen de asignación, confirmación y auditoría |
| AM-08 | Un excolaborador conserva sesiones o credenciales | 4 | 3 | 12 | Baja central y revocación inmediata |
| AM-09 | Un capturista extrae información masivamente | 4 | 3 | 12 | CSV desactivado, límites, alertas y marcas de agua |
| AM-10 | Un archivo original se abre conociendo o adivinando su dirección | 4 | 3 | 12 | Autorización por descarga y enlaces individuales de corta duración |
| AM-11 | Caché, cola o trabajo en segundo plano mezcla clientes | 4 | 3 | 12 | Tenant firmado y espacio aislado en cada capa |
| AM-12 | Una factura aprobada se modifica sin autorización | 4 | 3 | 12 | Permiso específico, motivo, versión y auditoría |
| AM-13 | La evidencia de auditoría se modifica o elimina | 4 | 3 | 12 | Bitácora inmutable y acceso separado |
| AM-14 | Una integración expone un token con acceso amplio | 4 | 3 | 12 | Identidad técnica por tenant, alcance mínimo y rotación |
| AM-15 | Un reporte consolidado mezcla o muestra clientes incorrectos | 4 | 2 | 8 | Servicio global separado y selección explícita |
| AM-16 | Un respaldo contiene datos accesibles de varios clientes | 4 | 2 | 8 | Cifrado, separación y acceso restringido |
| AM-17 | Los registros técnicos contienen salarios, recetas, tokens o importes sensibles | 3 | 3 | 9 | Enmascaramiento y lista de campos prohibidos |
| AM-18 | Un administrador de seguridad se concede acceso financiero | 4 | 2 | 8 | Separación administrativa y alerta inmediata |
| AM-19 | El creador aprueba su propio comprobante interno | 3 | 3 | 9 | Prohibición creador-aprobador |
| AM-20 | Soporte técnico consulta producción sin justificación | 4 | 2 | 8 | Acceso temporal, limitado y registrado |
| AM-21 | Un PDF, imagen o XLSX malicioso ataca el procesamiento | 3 | 3 | 9 | Validación, límites y procesamiento aislado |
| AM-22 | Una carga masiva agota almacenamiento o procesamiento | 3 | 3 | 9 | Cuotas por tenant y límites de concurrencia |
| AM-23 | Malware o un tercero controla el equipo de un usuario | 4 | 2 | 8 | Sesión corta, dispositivos confiables y alertas |
| AM-24 | Un usuario comparte una captura o reporte descargado | 4 | 2 | 8 | Marcas de agua, trazabilidad y política de dispositivos |
| AM-25 | Un proveedor o dependencia tecnológica es comprometido | 4 | 2 | 8 | Versiones controladas, escaneo y mínimo privilegio |
| AM-26 | Se pierde una clave de cifrado y no pueden recuperarse datos | 4 | 1 | 4 | Respaldo seguro de claves y restauración probada |
| AM-27 | Un ataque de disponibilidad impide la operación | 3 | 3 | 9 | Límites, protección perimetral y recuperación |
| AM-28 | Una importación asigna documentos a la sucursal o cliente incorrecto | 4 | 3 | 12 | Vista previa, tenant fijo y confirmación |
| AM-29 | Un cambio de rol no afecta sesiones ya abiertas | 4 | 3 | 12 | Revocación y autorización consultada en tiempo real |
| AM-30 | El director genera un consolidado mayor al necesario | 4 | 2 | 8 | Selección de alcance, reautenticación y auditoría |

## 4. Hallazgos sobre el estado actual

AM-02 y AM-03 existen en la demo porque todavía no hay autenticación y los identificadores de los actores se reciben como datos de la petición. Esto era una exclusión deliberada de la primera demo, pero constituye un bloqueo absoluto para producción.

AM-01 y AM-04 también bloquean producción porque el modelo actual todavía no contiene una entidad de tenant ni aislamiento entre grupos restauranteros.

AM-24 no puede eliminarse completamente por medios técnicos. Una persona autorizada puede fotografiar una pantalla. El riesgo se reduce mediante trazabilidad, marcas de agua, equipos administrados, capacitación y medidas operativas.

## 5. Contenido obligatorio de una amenaza

Al desarrollar cada amenaza, su registro deberá incluir:

- identificador y título;
- activo afectado;
- actor o atacante;
- escenario y condiciones necesarias;
- impacto y probabilidad iniciales;
- controles preventivos;
- método de detección;
- respuesta al incidente;
- prueba que demuestra el funcionamiento del control;
- riesgo residual después de los controles;
- responsable de implementar y revisar el tratamiento;
- estado; y
- fecha de la última revisión.

## 6. Condición para producción

Ninguna amenaza con riesgo inicial igual o mayor a 12 puede pasar a producción sin:

1. controles preventivos implementados;
2. detección y respuesta definidas;
3. pruebas satisfactorias;
4. riesgo residual documentado; y
5. aceptación expresa del responsable cuando permanezca riesgo residual relevante.
