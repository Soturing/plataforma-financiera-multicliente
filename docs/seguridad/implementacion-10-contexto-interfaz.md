# Implementación 10 — Contexto seguro de interfaz

Estado: **primera pantalla y contrato de selección implementados en rama**.
Fecha: 2026-09-02.

## Primera pantalla

Se creó un primer armazón visual para la aplicación segura. Mantiene la identidad visual existente e incorpora de forma permanente:

- identidad y rol efectivo de la sesión;
- nivel de autenticación;
- grupo restaurantero activo;
- sucursal activa o consolidado autorizado;
- módulos de navegación visibles según el alcance;
- explicación de los controles aplicados a cada solicitud; y
- estados preparados para sesión, autorización y reautenticación.

La vista se publica temporalmente en `/static/security-shell-preview.html`. Utiliza únicamente datos ficticios, lo indica en pantalla y no consume ni modifica la operación. Se mantuvo separada de `/` para no interrumpir la aprobación de facturas en curso.

## Contrato con el plano de control

`GET /api/v1/security/scope-options` devuelve los rótulos que la interfaz necesita antes de abrir un data plane:

- nombre de la identidad autenticada;
- identificador y nivel de la sesión;
- tenants activos o en sólo lectura que cubren sus asignaciones vigentes;
- roles y módulos aplicables a cada tenant; y
- exclusivamente las sucursales activas cubiertas por esas asignaciones.

El identificador de sucursal expuesto es el UUID del data plane que debe viajar en `X-Branch-Id`. Las credenciales, ubicaciones de archivos y referencias de conexión no forman parte de la respuesta.

Para un director global o administrador de seguridad global se enumeran los clientes disponibles para sus funciones de consultora. Un capturista sólo recibe los tenants asignados y, dentro de cada uno, las sucursales explícitas salvo que su asignación indique todas.

## Reglas de seguridad de la pantalla

- La selección del navegador no autoriza. Cada endpoint vuelve a comprobar identidad, sesión, tenant, módulo, sucursal y acción.
- La identidad y la sesión se revalidan en el plano de control al resolver las opciones.
- No se abre una conexión financiera para poblar el selector inicial.
- Cambiar de cliente deberá cancelar solicitudes pendientes y borrar filtros, selecciones y datos renderizados del cliente anterior.
- El token de acceso se mantendrá en memoria; no se guardará en `localStorage` ni `sessionStorage`.
- Ocultar un menú mejora la experiencia, pero el servidor continúa siendo la única autoridad de permisos.
- La consulta de capturistas permanece habilitada dentro de sus asignaciones conforme a la decisión provisional D-008.

## Pendiente para activación

La vista todavía no reemplaza la pantalla operativa. Para activarla faltan la elección del proveedor OIDC, el flujo real de inicio y cierre de sesión, la conexión del shell con `scope-options`, los estados 401/403/reautenticación y la adaptación progresiva de la bandeja actual al contexto seleccionado.

## Evidencia

- La suite completa en bases aisladas alcanzó `145 passed`; las pruebas que requieren credenciales adicionales quedaron omitidas de forma explícita.
- Las tres pruebas de integración del repositorio de control pasaron en una base desechable y verifican tanto el alcance limitado de un capturista como el acceso global del director a clientes activos y en sólo lectura.
- El contrato HTTP comprueba autenticación obligatoria y serialización exclusiva de rótulos resueltos en servidor.
- El JavaScript de la vista pasó validación de sintaxis, crea opciones con `textContent` y no usa almacenamiento web persistente.
