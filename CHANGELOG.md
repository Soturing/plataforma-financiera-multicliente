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
- **Despliegue en servidor (fase 7, D-026):** imagen del backend (`deploy/app/Dockerfile`), app y workers en
  contenedor por cliente con secretos de OpenBao al arrancar, archivos cifrados con gocryptfs, proxy Caddy con
  TLS, plano de control de producción, preparación de Ubuntu, arranque tras reinicio y temporizadores de
  respaldo, restauración e inactividad. Recomendación de VPS y bucket y guía en
  `docs/seguridad/despliegue-servidor.md`.
- **Auditoría de sólo anexado (migración 034, D-027):** las correcciones, los cambios de catálogo y los
  documentos eliminados ya no se pueden modificar ni borrar, ni siquiera con la cuenta propietaria; una
  factura con correcciones ya no se puede eliminar (la bandeja lo avisa en lugar de borrar su historial).
- **`python -m app.plataforma.tenants migrar --clave <CLIENTE>`:** aplica las migraciones pendientes a un
  cliente ya dado de alta.
- **Integración continua** (`.github/workflows/ci.yml`): suite completa contra una base desechable con RLS,
  búsqueda de secretos con gitleaks y escaneo informativo de dependencias y código.
- **Hoja de ruta integrada** con la auditoría de seguridad y de base de datos (`docs/roadmap-producto.md`).

### Seguridad (etapa 2 del roadmap)

- **Un solo aplicador de migraciones (§3.7.3):** `app/migraciones.py` lo usan los clientes (`tenants`), la base
  desechable del CI y la base de desarrollo (`python -m app.migraciones aplicar --url ...`, con
  `--semilla ARCHIVO@NNN` para los datos de demostración y `--hasta-previas NNN` para adoptar una base ya
  migrada). El `compose.yaml` de desarrollo ya no monta archivos sueltos en `initdb.d`: una migración nueva sólo
  necesita su archivo en `db/migrations/`.
- **Rutas relativas y nombres de archivo limpios (§3.6.8):** `archivo_url`, `archivo_original_url` y
  `evidencia_url` se guardan relativos al directorio de archivos del cliente (`lotes/<id>/pagina-1.pdf`), no con
  la ruta absoluta del servidor; las rutas absolutas ya guardadas siguen funcionando. Los nombres que manda el
  cliente se limpian (sin directorios, comillas, `;` ni caracteres de control) al guardarlos y en
  `Content-Disposition` (`app/storage.py`: `ruta_para_guardar`, `ruta_almacenada`, `nombre_seguro`).
- **Identidad estable junto a cada `*_por` (migración 035, §3.8.2):** las 29 columnas de operador de `audit`,
  `catalog`, `core` y `finance` ganan un `<col>_id uuid` con el identificador de la identidad en el plano de
  control. La app declara `app.identidad` al abrir la conexión y un trigger (`seguridad.completar_identidad`)
  lo copia cuando se escribe o cambia la etiqueta; sin sesión (workers, modo abierto) queda vacío, y las filas
  anteriores no se rellenan. Una prueba avisa si se añade un `*_por` sin su `_id`.
- **Topes de `tenant_runtime` (§3.8.3):** `statement_timeout` de 120 s e `idle_in_transaction_session_timeout`
  de 60 s, fijados al crear los roles y con `tenants migrar` en los clientes existentes.
- **`bandit` limpio y bloqueante:** los 52 hallazgos se resolvieron o se justificaron con `# nosec` (consultas
  armadas con literales del código, parámetros de la API de OpenBao, bind en contenedor); `bandit.yaml` omite sólo
  B404/B603/B607 (uso de `subprocess` con lista de argumentos). El job `escaneo` del CI deja de ser informativo.
- **XML:** `xml_seguro` busca `DOCTYPE`/`ENTITY` en todo el contenido (antes sólo en los primeros 8 KB, y un
  comentario largo lo esquivaba) y rechaza UTF-16/UTF-32; el lector de CFDI (`text_processing`) usa el mismo helper.

- **Dependencias de desarrollo separadas (§3.7.2):** `requirements-dev.txt` (incluye `requirements.txt` más
  `pytest`, `pip-audit` y `bandit`, con versión fija). `pytest` sale de `requirements.txt`, así que la imagen
  de producción ya no lo instala. El CI y la guía de instalación usan el archivo de desarrollo.

- **Firma real de los archivos subidos (§3.6.4):** además del tipo que declara el cliente, se comprueban los
  primeros bytes (PDF, JPEG, PNG, WEBP, XML, XLSX y texto para CSV/TSV); un ejecutable, un HTML o un ZIP con otro
  nombre se rechazan con 415 y no quedan en disco. El archivo se guarda con la extensión que corresponde a su
  contenido, no con la del nombre que manda el cliente (`app/firma_archivos.py`). ClamAV sigue pendiente.

- **Límites de recursos (§3.6.7):** límite de peticiones por IP y por minuto (1200 en general, 30 en `/auth/*`,
  configurable con `FACTURAS_LIMITE_PETICIONES_POR_MINUTO` y `FACTURAS_LIMITE_ACCESO_POR_MINUTO`, 0 lo apaga) con
  respuesta 429 y `Retry-After`; el catálogo de proveedores y los archivos de ventas se leen por partes y se
  cortan en el límite sin cargarse enteros; el compose del servidor fija memoria, CPU y procesos máximos para la
  app y los workers (`APP_MEM_LIMIT`, `APP_CPUS`, `WORKERS_MEM_LIMIT`, `WORKERS_CPUS`).

- **El acceso es seguro por defecto (D-028):** `FACTURAS_ACCESO_MODO` vale `seguro` si no se declara, y con
  `FACTURAS_ENVIRONMENT=produccion` la app no arranca en modo abierto. Para revisar pantallas sin sesión en
  desarrollo hay que escribir `FACTURAS_ACCESO_MODO=abierto` en el `.env`.

- Cabeceras de seguridad en cada respuesta de la aplicación: Content-Security-Policy (sólo scripts del propio
  origen), `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy` y
  `Permissions-Policy` (`app/endurecimiento.py`).
- Los archivos subidos se muestran en línea sólo si son PDF o imagen; cualquier otro tipo (p. ej. XML) se
  descarga (`Content-Disposition: attachment`).
- `/docs` y `/openapi.json` sólo con `environment` distinto de `produccion` y `acceso_modo` abierto.

### Corregido

- El catálogo de proveedores en XLSX rechaza declaraciones XML (`DOCTYPE`/`ENTITY`) y los XLSX de proveedores
  y de ventas se rechazan si descomprimidos superan 50 MB.
- PostgreSQL del `compose.yaml` de desarrollo sólo escucha en `127.0.0.1`.
- Dependencias con CVE conocidos según `pip-audit`: `pypdf` 6.21.1, `starlette` 1.3.1 (vía `fastapi` 0.136.3,
  que se mantiene así porque la 0.146 cambia `app.routes` y rompe la clasificación de rutas), `python-multipart`
  0.0.31 y `pytest` 9.0.3.

- `numpy` y `Pillow` se importaban sin estar declarados en `requirements.txt`.

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
