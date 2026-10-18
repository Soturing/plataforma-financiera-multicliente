# Historial de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado
[MAYOR.MENOR.PARCHE](docs/versionado.md). La versión vigente está en el archivo `VERSION`.

## [Sin publicar]

### Agregado

- **Proveedor de identidad (fase 1, D-021):** Keycloak autoalojado en el perfil `identidad` de `compose.yaml`
  con realm versionado sin contraseñas: llave física FIDO2 para roles globales, passkey o código de recuperación
  para el resto y alta sólo por invitación. Prueba técnica automatizada en `tests/identidad/`; resultados y
  bloqueos de producción en `docs/seguridad/fase1-identidad.md`. Todavía no está conectado a la aplicación.

## [0.1.0] - 2026-10-18

Primera versión numerada de la línea de desarrollo hacia el MVP, sobre la base saneada.

### Agregado

- **Categorías de gasto (D-017):** nueve categorías fijas con subcategorías editables; sin centros de costo.
- **Lista de gastos fijos** con alta previa del proveedor, comisiones con proyección y cierre real mensual, y
  nómina capturada a mano por semana y sucursal.
- **Lectura de facturas v2:** OCR de imagen para PDF escaneados, lectura del QR del SAT, extracción con
  contexto del grupo (RFC validado con su dígito verificador, importe con letra, folio por etiquetas) y
  clasificación de tickets, notas, remisiones y cotizaciones. Ver `docs/ocr-lectura-v2.md`.
- **Aviso de posible duplicado** (ticket y factura = un solo gasto) y razones sociales propias del grupo
  (`/api/v1/entidades-propias`).
- **Cola de lectura OCR** con workers permanentes (`docs/cola-ocr.md`).
- **Páginas de una misma factura:** la página sin totales se liga a la principal y sale de la bandeja
  (`/api/v1/continuaciones/{id}/separar`).
- **Confianza por campo** en la revisión: los campos que la lectura no pudo confirmar se resaltan y la bandeja
  cuenta los pendientes de revisar.
- **Pantalla de razones sociales del grupo** en Catálogos.
- Versionado semántico, `CHANGELOG.md` y versión visible en `/health` y en el menú.

### Cambiado

- Límite de carga de archivos: 100 MB.
- La plantilla de proveedores se genera desde el catálogo vigente.

### Migraciones

- 024 a 031. En bases existentes se aplican a mano; `compose.yaml` solo las ejecuta en un volumen vacío.
