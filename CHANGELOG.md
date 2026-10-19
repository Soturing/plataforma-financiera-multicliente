# Historial de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado
[MAYOR.MENOR.PARCHE](docs/versionado.md). La versión vigente está en el archivo `VERSION`.

## [Sin publicar]

### Agregado

- **Proveedor de identidad (fase 1, D-021):** Keycloak autoalojado en el perfil `identidad` de `compose.yaml`
  con realm versionado sin contraseñas: llave física FIDO2 para roles globales, passkey o código de recuperación
  para el resto y alta sólo por invitación. Prueba técnica automatizada en `tests/identidad/`; resultados y
  bloqueos de producción en `docs/seguridad/fase1-identidad.md`.
- **Usuarios y acceso seguro (fases 2–4):** inicio de sesión con passkey o llave física desde la barra superior,
  elección de rol, pantalla **Usuarios y accesos** (`#/accesos`) con invitaciones, suspensión, cierre de
  sesiones y bitácora inmutable encadenada; menú filtrado por rol; autorización en el servidor para las 86
  rutas; autor de cada operación tomado de la sesión. Modo abierto por defecto (D-022). Detalle y guía en
  `docs/seguridad/fases2-4-acceso.md`.
- **Data plane por cliente (fase 5, D-024):** cada administración tiene su propio stack (base, volumen, red,
  credenciales y archivos) creado con `python -m app.plataforma.tenants alta`; restaurantes formales
  (`catalog.restaurantes`, migración 032); RLS forzado por tenant y sucursal con cuenta sin privilegios
  (migración 033); alcance de las personas por restaurante completo o por sucursal. El 8010 ya usa el data plane
  propio de `GRUPO-DEMO`. Detalle en `docs/seguridad/fase5-data-plane.md`.
- **Ciclo de vida de las personas (fase 6):** ficha de persona en "Usuarios y accesos" con roles y alcance
  (agregar, cambiar, revocar), autenticadores, sesiones, recuperación asistida con espera de 24 h, suspensión,
  reactivación, baja verificada y reingreso; sección "Mi cuenta" para agregar o dar de baja autenticadores;
  bloqueo tras entrar con código de recuperación hasta registrar una passkey nueva (método de acceso por `amr`);
  avisos por correo y tarea de inactividad. Detalle en `docs/seguridad/fase6-ciclo-vida.md`.
- **Secretos, claves por cliente y respaldos (fase 7, D-025):** OpenBao con desbloqueo manual y claves Transit
  por cliente; las contraseñas de las bases salen de los archivos privados; respaldos diarios cifrados con restic
  (un repositorio por cliente, destino sólo anexado) y restauración de prueba en una base desechable.
  Detalle en `docs/seguridad/fase7-secretos-respaldos.md`.

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
