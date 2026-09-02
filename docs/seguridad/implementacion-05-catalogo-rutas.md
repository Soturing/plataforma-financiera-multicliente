# Implementación 05 — Catálogo cerrado de rutas de negocio

Estado: **catálogo implementado; conexión de handlers iniciada en la implementación 06**.
Fecha: 2026-09-01.

## Objetivo

Evitar que una ruta financiera existente o futura quede fuera del modelo de permisos por omisión.

## Cobertura

Las 59 combinaciones actuales de método y ruta bajo `/api/v1/`, excluyendo únicamente el router de seguridad, declaran explícitamente:

- una o más acciones del catálogo de permisos;
- modo de acceso de lectura o escritura;
- forma de obtener o comprobar la sucursal; y
- campos de actor que hoy llegan desde el navegador y deben eliminarse.

La prueba compara el catálogo contra las rutas reales registradas por FastAPI. Agregar, eliminar o renombrar un endpoint sin actualizar su clasificación rompe la suite.

## Resolución de sucursal

Cada ruta utiliza una de estas estrategias futuras de enlace:

- tenant completo;
- sucursal recibida en formulario;
- sucursal recibida en query;
- UUID de sucursal dentro del cuerpo;
- consulta del recurso por su identificador;
- consulta de varios recursos; o
- colección filtrada obligatoriamente por RLS.

La estrategia no confía en el valor recibido. Sirve para indicar qué dato debe resolver el backend y comparar con el contexto ya autorizado antes de ejecutar el handler.

## Acciones compuestas

Una ruta puede requerir más de una acción. Por ejemplo, el catálogo operativo combinado devuelve proveedores y catálogos contables, por lo que deberá comprobar ambos permisos y no utilizar el permiso más amplio de forma implícita.

## Actores no confiables

Veinte rutas todavía reciben alguno de estos campos desde el navegador:

`actualizada_por`, `actualizado_por`, `autorizada_por`, `cancelado_por`, `creada_por`, `creado_por`, `descartado_por`, `eliminado_por`, `importado_por`, `rechazada_por`, `registrada_por`, `revisada_por` y `rol_creador`.

El catálogo los marca como deuda de migración. En modo seguro deberán ignorarse o desaparecer del contrato; identidad y rol se obtendrán exclusivamente de la sesión verificada.

## Falla cerrada

El catálogo no activó por sí solo la seguridad sobre la demo. La implementación 06 conecta el primer subconjunto y utiliza este inventario como lista cerrada: las rutas aún no integradas se deniegan cuando el modo seguro está activo.

Antes de habilitar modo seguro:

1. el resolvedor de sucursal debe implementarse para cada estrategia;
2. cada handler debe recibir la conexión desde el router autorizado;
3. los actores del navegador deben sustituirse por la identidad efectiva; y
4. una ruta ausente o ambigua debe responder con denegación, no usar la conexión demo.

## Evidencia

- las 59 rutas de negocio coinciden exactamente con 59 políticas;
- todas las acciones referenciadas existen en el catálogo ejecutable;
- ninguna ruta carece de estrategia de sucursal; y
- los trece nombres de actor enviados por el navegador están inventariados.

Con esta entrega la suite completa alcanza **149 pruebas aprobadas**.
