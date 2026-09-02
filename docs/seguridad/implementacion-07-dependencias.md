# Implementación 07 — Dependencias que procesan entradas no confiables

Fecha: 2026-09-02.

## Objetivo

Evitar que un PDF o formulario manipulado pueda bloquear el servicio, agotar memoria o escribir fuera del directorio previsto aprovechando vulnerabilidades conocidas de terceros.

## Decisión aplicada

- `python-multipart` queda fijado en `0.0.31`.
- `pypdf` queda fijado en `6.14.2`.
- `pytest` queda fijado en `9.0.3` para eliminar el manejo inseguro de directorios temporales de versiones anteriores.
- Dependabot revisará semanalmente el manifiesto de Python y podrá abrir hasta cinco propuestas simultáneas.
- No se habilita fusión automática: cada actualización debe pasar revisión y pruebas aisladas antes de incorporarse.

Las versiones se eligieron a partir de los límites corregidos indicados en las alertas del repositorio. El cambio cubre las cinco alertas altas observadas y las alertas relacionadas con esas mismas versiones de `pypdf` y `python-multipart`; GitHub cerrará las alertas únicamente cuando el cambio llegue a la rama predeterminada y vuelva a analizar el manifiesto.

## Verificación

- `pip check`: sin requisitos incompatibles.
- Versiones importadas: `pypdf 6.14.2`, `python-multipart 0.0.31` y `pytest 9.0.3`.
- Suite ejecutada contra PostgreSQL temporal y directorio de cargas aislado: `139 passed`, `19 skipped`.
- Las 19 pruebas omitidas son integraciones que requieren los data planes sintéticos dedicados; no se conectó la suite a la base local usada por el operador.

## Regla operativa

Una alerta alta o crítica en una dependencia que procese archivos, autenticación, autorización, cifrado o acceso a base de datos bloquea nuevas entregas funcionales hasta ser corregida o aceptada formalmente con mitigaciones y fecha de caducidad.
