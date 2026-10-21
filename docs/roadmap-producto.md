# Hoja de ruta del producto

Actualizada: 2026-10-19. Integra cuatro fuentes:

- la hoja de ruta anterior (frentes 1 a 5);
- el plan de seguridad por fases ([seguridad/plan-implementacion.md](seguridad/plan-implementacion.md), fases 1 a 7);
- la auditoría estática de GitHub Copilot del 2026-10-19 (16 hallazgos de seguridad y 11 de arquitectura);
- la revisión de base de datos de Copilot del 2026-10-19 (17 mejoras sobre 23 migraciones).

> **Importante sobre la auditoría.** Copilot revisó la base saneada (`main`, commit `e794699`), que no tiene nada del trabajo de octubre. Cada hallazgo se volvió a comprobar contra la rama más avanzada, `claude/roadmap-usuarios-seguridad-8e43ba` (PR #2, que ya contiene `migrate-legacy`). La columna «Estado real» de §2 refleja esa rama, no `main`. La revisión de base de datos contó 23 migraciones; la rama tiene 33 más las 4 del plano de control (`db/control`).

## 1. Estado de los frentes

| # | Frente | Estado | Dónde |
|---|--------|--------|-------|
| 1 | Usuarios y acceso con alta seguridad | **Hecho en rama**, fases 1–7 (Keycloak con passkeys, plano de control, sesiones, autorización por ruta, ciclo de vida, OpenBao, respaldos). Sin desplegar. Corre en **modo abierto** (D-022). | PR #2 |
| 2 | Bloqueo por falta de pago | Pendiente. El modelo de tenant ya existe (D-024), así que el estado de servicio se puede colgar del plano de control. | — |
| 3 | Cambio de reportes | Pendiente: esperando la nueva definición del usuario. | — |
| 4 | Sistema reutilizable para distintos restaurantes | **Aislamiento hecho en rama** (stack por cliente, RLS con `FORCE`, D-024/D-026). Falta la configuración de marca por cliente y la plantilla de alta sin tocar código. | PR #2 |
| 5 | Rediseño de la navegación | Anotado; sin diseñar. | — |
| 6 | **Endurecimiento de la aplicación** *(nuevo, sale de la auditoría)* | Pendiente. Ver §3.6. | — |
| 7 | **Calidad e ingeniería** *(nuevo, sale de la auditoría)* | Pendiente. Ver §3.7. | — |
| 8 | **Integridad de la base de datos** *(nuevo, sale de la revisión de base de datos)* | Pendiente. Ver §3.8. | — |
| 0 | **Integración de ramas** *(nuevo, bloquea todo lo demás)* | **Hecho** (2026-10-19): PR #2 fusionado en `main` (`f2dcf23`). Queda archivar `codex/security-foundation`. Ver §3.0. | PR #2 |

## 2. Conciliación de la auditoría de Copilot

Estados: **Resuelto** (ya está en la rama de seguridad), **Parcial** (resuelto en parte o sólo en el servidor), **Abierto** (sin cambios).

### 2.1 Seguridad

| # | Sev. | Hallazgo de Copilot | Estado real | Lo que falta | Frente |
|---|------|---------------------|-------------|--------------|--------|
| 1 | Crítica | Sin autenticación ni autorización | **Parcial.** Keycloak, sesiones en el plano de control y política por ruta (`app/seguridad/politica.py`) están hechos, pero `acceso_modo` vale `"abierto"` por defecto (`app/config.py:32`): sin sesión la app sigue respondiendo como antes. | Cambiar el valor por defecto a `"seguro"` y retirar el modo abierto antes de producción. | 1 |
| 2 | Crítica | Sin aislamiento multicliente | **Resuelto.** Base, archivos y workers propios por cliente; `tenant_id` y RLS con `FORCE` (migración 033); prueba con dos tenants. | Llevar las pruebas de fuga a la integración continua (§3.7). Red propia por cliente entre proxy y app (ya pendiente). | 4 |
| 3 | Alta | Acciones destructivas con identidad falsificable | **Resuelto con sesión** (corrección del 2026-10-19: el diagnóstico anterior de «hueco confirmado» era incorrecto). `autorizar_ruta` reemplaza todos los campos `*_por` del JSON por la identidad de la sesión (`_sustituir_autor`) y los formularios usan `actor_o()`; lo comprueba `test_autorizacion.py`. Sólo en modo abierto, sin sesión, el autor sigue llegando del navegador. Los archivos físicos se siguen borrando. | Salir del modo abierto (3.1). Hecho: prueba que falla si aparece un `*_por` anidado o un formulario sin `actor_o`. Pendiente: reautenticación C2 y retención de archivos borrados. | 6 |
| 4 | Alta | XML sin protección XXE / *billion laughs* | **Resuelto** (etapa 1). El CFDI ya rechazaba `DOCTYPE`/`ENTITY`; ahora también el XLSX de proveedores (`app/xml_seguro.py`), y ambos XLSX (proveedores y ventas) comprueban el tamaño descomprimido antes de abrirse (50 MB). Se descartó `defusedxml`: sin versiones nuevas desde 2021, y Python 3.12 ya no resuelve entidades externas. | — | 6 |
| 5 | Alta | Validación de archivos sólo por `Content-Type` | **Abierto.** `app/storage.py` confía en el tipo y la extensión que manda el cliente. | Comprobar la firma real del archivo; antivirus (ClamAV) en el worker. | 6 |
| 6 | Alta | Sin límite de tasa ni de recursos | **Parcial.** Lo del `Popen` por factura ya se resolvió: ahora hay una cola en PostgreSQL con workers permanentes (030). Límite unificado en 100 MB (`config.py` y `.env.example` coinciden). Siguen abiertos: el límite de peticiones, la carga de ventas que lee el archivo entero en memoria (`main.py:823` y `:1118`) y los límites de CPU y memoria de los workers. | Límite de peticiones en Caddy o con `slowapi`, ventas leídas por partes, `cpus`/`mem_limit` en el compose del servidor, cuota por cliente. Revisar si 100 MB es el tope correcto. | 6 |
| 7 | Media | Faltan cabeceras; archivos servidos `inline` | **Parcial.** El Caddyfile del servidor ya pone HSTS, `nosniff`, `X-Frame-Options`, `Referrer-Policy` y `Permissions-Policy`. Falta CSP; en local no hay cabeceras; los archivos subidos se siguen sirviendo `inline` (`main.py:333`, `:485`, `:656`). | CSP estricta, middleware de cabeceras en la app y `attachment` para todo lo que no sea PDF o imagen. | 6 |
| 8 | Media | Uso extenso de `innerHTML` | **Abierto, y peor:** 84 usos en `app.js` (148 KB). | Revisar cada uso, pasar a `textContent`, ESLint con regla de seguridad. CSP como red de seguridad. | 6 / 7 |
| 9 | Media | Rutas absolutas en la base; nombre original en `Content-Disposition` | **Abierto.** | Guardar rutas relativas al directorio del cliente y limpiar `filename`. | 6 |
| 10 | Media | Sin cifrado en reposo; PostgreSQL en `0.0.0.0:5432` | **Resuelto** (etapa 1). gocryptfs por cliente y respaldos cifrados (D-025, D-026); el `compose.yaml` de desarrollo ya publica PostgreSQL sólo en `127.0.0.1`. | TLS hacia la base si alguna vez sale del host. | 6 |
| 11 | Media | Una sola cuenta de base con privilegios de dueño | **Resuelto en el data plane.** La cuenta de ejecución no es dueña de las tablas ni tiene `BYPASSRLS` (033, `db/control/000_roles.sh`). | Asegurar que la base compartida antigua (5432/5434) nunca llegue a producción. | 1 |
| 12 | Media | `except Exception` genérico; sin logging estructurado | **Parcial.** La bitácora de seguridad (sólo anexado, encadenada por hash) cubre accesos y acciones sensibles. Falta logging JSON con ID de correlación; quedan unos 15 `except Exception`. | Logging estructurado y el tablero de alertas (ya pendiente en el frente 1). | 7 |
| 13 | Baja | SQL dinámico con f-strings (hoy con lista blanca) | **Abierto.** | `psycopg.sql.Identifier` y una prueba de la lista blanca. | 7 |
| 14 | Baja | `/docs` y `/openapi.json` públicos | **Abierto.** | Apagarlos en modo seguro y en producción. | 6 |
| 15 | Baja | Dependencias sin escanear; `pytest` en producción | **Parcial.** Dependabot está activo en GitHub y ya hay un `requirements-operacion.txt`. `pytest` sigue en `requirements.txt`. | `pip-audit` en la integración continua, `requirements-dev.txt` y versiones con hash. | 7 |
| 16 | Baja | `.cmd` con `-ExecutionPolicy Bypass`; sin HTTPS | **Parcial.** En el servidor ya hay Caddy con TLS automático. El `.cmd` sólo se usa en la laptop de desarrollo. | Nada urgente; firmar los scripts si se distribuyen. | — |

### 2.2 Arquitectura y calidad

| # | Hallazgo de Copilot | Estado real | Lo que falta |
|---|---------------------|-------------|--------------|
| 1 | Archivos gigantes | **Abierto, y crecieron:** `main.py` 52 KB, `repository.py` 73 KB, `app.js` 148 KB. | Separar en `APIRouter` por módulo y en módulos de JS. Hacerlo **después** de integrar las ramas. |
| 2 | Migraciones montadas a mano en compose | **Parcial.** Los data planes usan `aplicar_migraciones` con la tabla `migraciones_aplicadas` (`app/plataforma/tenants.py`). El `compose.yaml` de desarrollo sigue montando archivos sueltos. | Usar el mismo aplicador en desarrollo y retirar los montajes. |
| 3 | `Popen` como cola de trabajos | **Resuelto** (cola OCR, 030). El `Popen` que queda en `jobs.py` sólo arranca workers en local. | — |
| 4 | Sin integración continua | **Abierto.** No existe `.github/workflows`. | GitHub Actions: `pytest`, `ruff`, `pip-audit`, `bandit`, `gitleaks` y las pruebas de aislamiento. |
| 5 | Faltan pruebas de autorización, aislamiento, archivos maliciosos y carga | **Parcial.** 252 pruebas, incluidas autorización y aislamiento con dos tenants. Faltan archivos maliciosos, carga y medición de cobertura. | Agregar esas tres. |
| 6 | Frontend sin tipado ni lint | **Abierto.** | ESLint primero; TypeScript se decide junto con el rediseño de navegación (frente 5). |
| 7 | Configuración inconsistente | **Parcial.** Límite de carga unificado; existe `acceso_modo`. Falta un perfil de producción que apague docs y modo abierto. | Un único interruptor `entorno=produccion`. |
| 8 | Dinero con `float` | **Casi resuelto.** `accounting.py` no usa `float`. `financial_reports.py:458-459` lo usa sólo para la serie de la gráfica. | Confirmar que no se recalcula nada con esos valores; pruebas de redondeo. |
| 9 | OCR sin aislar | **Parcial.** Workers en contenedor por cliente con usuario sin privilegios. | Límites de CPU y memoria, y sin salida a internet. |
| 10 | Observabilidad | **Abierto** (coincide con el tablero de alertas pendiente). | Métricas básicas de la cola y de errores, y alertas. |
| 11 | Contenedorización | **Resuelto** (`deploy/app/Dockerfile` con `USER facturas`, stack por cliente). | Sistema de archivos de sólo lectura en el contenedor. |

### 2.3 Base de datos

La diferencia de fondo: Copilot propone aislar con `organizacion_id` y RLS sobre una base compartida. La rama eligió **una base por cliente** (D-024, vía 4): la base guarda la clave de su tenant en `seguridad.identidad_tenant`, cada conexión declara `app.tenant` y `app.sucursales`, y sin esas variables no ve ni escribe nada (falla cerrada). Por eso las unicidades globales (`proveedores_rfc_unico`, `sucursales_rfc_unico`) ya son, en la práctica, unicidades por cliente, y **no hace falta añadir `organizacion_id`**.

| # | Sev. | Mejora propuesta | Estado real | Lo que falta | Frente |
|---|------|------------------|-------------|--------------|--------|
| 1 | Crítica | `organizacion_id` y RLS | **Resuelto de otra forma** (base por cliente y RLS con `FORCE` por tenant y sucursal, migración 033). | Nada en el esquema. Ver el punto 16 sobre la base de desarrollo. | 4 |
| 2 | Crítica | Roles `app_rw` / `migrator` / `readonly` | **Resuelto en su mayoría.** `tenant_owner` (migraciones) y `tenant_runtime` (app, sin propiedad ni `BYPASSRLS`); `REVOKE CREATE ON SCHEMA public`. | Un rol de sólo lectura para reportes, si llega a hacer falta. | 8 |
| 3 | Crítica | Identidad guardada como texto libre | **Abierto.** Hay 28 columnas `*_por text` (`creado_por`, `revisada_por`, `eliminado_por`, `aprobada_por`, etc.). Las identidades viven en el plano de control, que es otra base, así que no se puede poner una FK directa. | Guardar el ID estable de la identidad (UUID del plano de control) junto a la etiqueta y llenarlo siempre desde la sesión. Va de la mano con el hallazgo de seguridad 3. | 8 |
| 4 | Crítica | Auditoría que se puede modificar; `CASCADE` sobre datos financieros | **Resuelto** (etapa 1, migración 034). `audit.correcciones` pasa a `ON DELETE RESTRICT` (una factura con correcciones no se borra; la bandeja responde 409 con un mensaje claro). Triggers de sólo anexado en `correcciones`, `cambios_catalogo` y `documentos_eliminados` (y sin `DELETE` en `aprendizajes`) también para la propietaria; la única salida es `audit.purga=on` declarada por la propietaria (limpieza de pruebas y futura retención). | Borrado lógico de facturas: se pasa a la etapa 2; hoy sólo se borran documentos pendientes y cada borrado queda en `audit.documentos_eliminados`. | 8 |
| 5 | Alta | Rutas absolutas en `archivo_url` / `evidencia_url` | **Abierto** (`archivo_url`, `archivo_original_url`, `evidencia_url`). | `storage_key` relativo al volumen del cliente. Coincide con el hallazgo de seguridad 9. | 6 |
| 6 | Alta | Migraciones sin control de versión; `DELETE`/`DROP` dentro de migraciones | **Parcial.** Los data planes llevan la tabla `migraciones_aplicadas`. El compose de desarrollo sigue montando archivos sueltos. Hay `DROP TABLE` y borrados de datos en migraciones (p. ej. `024` elimina `centros_costo`, D-017). | Un solo aplicador (ya en §3.7) y una regla: migración destructiva sólo con respaldo previo y prueba de restauración. | 7 |
| 7 | Alta | Estados en enums rígidos | **Abierto, prioridad baja.** Siete enums (`estado_factura`, `estado_trabajo_ocr`, etc.). | Trigger de transiciones válidas para `estado_factura`; cambiar a tablas de catálogo sólo si los estados empiezan a variar por cliente. | 8 |
| 8 | Alta | Integridad financiera con `CHECK` y triggers | **Parcial.** Todos los importes son `numeric(14,2)` y no hay `float`; existen `CHECK` de no negativos y `total > 0`. Faltan las reglas de suma. | `CHECK` de `total = subtotal - descuento + iva + otros_impuestos` (con la tolerancia de centavos que acepte el SAT), `periodo_desde <= periodo_hasta`, triggers diferidos de sumas (periodificación y distribución de comprobantes) y `EXCLUDE` contra periodos que se enciman. **Antes**, medir cuántas filas actuales violarían cada regla. | 8 |
| 9 | Alta | Datos de prueba mezclados con reales | **Parcial.** El alta de clientes (`tenants`) no carga `db/seeds/001_demo_catalogs.sql`; sólo lo hace el compose de desarrollo. `finance.ventas.es_demo` sigue existiendo. | Confirmar en la guía de despliegue que ningún cliente real recibe la siembra; decidir si `es_demo` se retira. | 8 |
| 10 | Media | Índices faltantes en FK hijas y en `audit.*` por fecha; `pg_trgm` | **Abierto.** No hay `pg_trgm` ni índices de similitud. | Medir con `EXPLAIN` sobre un volumen realista (24 000 documentos por semana) antes de crear índices; `pg_trgm` para la búsqueda de alias de proveedor. | 8 |
| 11 | Media | `archivo_sha256` sin unicidad | **Abierto a propósito.** Hoy un archivo repetido se detecta como duplicado y se avisa (regla «ticket + factura = un gasto»); un `UNIQUE` lo rechazaría en lugar de avisar. | Evaluar un índice único parcial sólo para facturas finales vigentes, no en la carga. | 8 |
| 12 | Media | JSONB sin esquema | **Abierto.** | `CHECK (jsonb_typeof(...) = 'object')` como mínimo; sacar el JSON pesado del OCR a archivo si crece. | 8 |
| 13 | Media | Vistas de analytics | **Abierto.** | Vistas materializadas sólo si `EXPLAIN` muestra que hace falta; depende también del frente 3 (reportes nuevos). | 3 / 8 |
| 14 | Media | Volumen: particionar y retener | **Abierto.** | Política de retención primero (obligación fiscal: 5 años); particionar `ocr.resultados`, `core.validaciones` y `audit.*` cuando el volumen lo pida. | 8 |
| 15 | Media | Cifrado y respaldos | **Resuelto en su mayoría.** Respaldos cifrados con Object Lock y prueba de restauración (D-025); disco con gocryptfs (D-026). | `pgAudit` y cifrado de columnas (RFC, nómina) sólo si un cliente o la ley lo exige. | 1 |
| 16 | Media | Operación: `127.0.0.1`, TLS, timeouts | **Parcial.** Las bases de cliente y de control sólo escuchan en `127.0.0.1`; la base de desarrollo no (hallazgo de seguridad 10). No hay `statement_timeout` ni `idle_in_transaction_session_timeout`. | Ponerlos en `tenant_runtime` (`ALTER ROLE ... SET`). | 8 |
| 17 | Media | Sólo existe una prueba de humo de la base | **Parcial.** Las pruebas de RLS y aislamiento corren desde `pytest` (252 pruebas); en `db/tests` sólo está `001_pipeline_smoke.sql`. | Pruebas de restricciones, triggers y cascadas (pgTAP o `pytest`; lo que resulte más simple). | 7 / 8 |

Correcciones al diagrama de la revisión: `catalog.centros_costo` ya no existe (D-017, migración 024), y faltan las tablas añadidas después (comisiones y nómina 025-027, cola OCR 030, grupos de páginas 031, restaurantes 032, `seguridad.*` 033).

## 3. Detalle de los frentes

### 3.0 Integración de ramas (nuevo; bloquea el resto)

Hoy hay tres líneas sin fusionar: `main` (base saneada), `codex/security-foundation` (legado, **no se reutiliza**) y `claude/roadmap-usuarios-seguridad-8e43ba` (PR #2, que ya incluye `migrate-legacy`). La auditoría encontró todo esto «sin implementar» precisamente porque `main` está atrasada.

- ~~Revisar y fusionar el PR #2 en `main`~~ **Hecho (2026-10-19).** El PR cambió de base de `claude/migrate-legacy-project-d73050` a `main` y se fusionó con merge commit `f2dcf23`. Al integrarlo se actualizaron `pypdf` (6.21.1), `starlette` (1.3.1), `python-multipart` (0.0.31) y `pytest` (9.0.3). `fastapi` quedó en **0.136.3**: la 0.146 envuelve los routers en `_IncludedRouter` y rompe `tests/seguridad/test_politica.py`. `pruebas` (bloqueante) pasa en CI; `escaneo` (bandit) sigue en rojo y no bloquea (ver etapa 2).
- Archivar `codex/security-foundation` con una nota en `decisiones.md` y cerrar los worktrees viejos. **Pendiente.**
- Después, volver a correr la auditoría (Semgrep, Bandit, `pip-audit`) sobre `main` ya integrada.

### 3.1 Usuarios y acceso — lo que queda

Hecho: fases 1 a 7 en local (ver el plan de seguridad). Pendiente, ahora con lo que aportó la auditoría:

- **Salir del modo abierto** (hallazgo 1): `acceso_modo="seguro"` por defecto; el modo abierto queda sólo como opción explícita en desarrollo.
- Contratar el VPS y el bucket, y ejecutar la guía de despliegue (`seguridad/despliegue-servidor.md`).
- Red propia por cliente entre proxy y app; SMTP real; URLs de Keycloak por cliente.
- Modelo de llave física; revisión periódica de accesos; tablero de alertas.
- Prueba de penetración externa, **después** de cerrar el frente 6 (si no, el pentest encontrará lo mismo que Copilot).

### 3.2 Bloqueo por falta de pago

Sin cambios de fondo. Ahora se apoya en el plano de control: el estado de servicio vive en el tenant y lo valida el mismo middleware de autorización. Requiere salir del modo abierto (3.1).

### 3.3 Cambio de reportes

Sin cambios: esperando la definición del usuario.

### 3.4 Sistema reutilizable — lo que queda

Aislamiento de datos resuelto. Falta:

- Configuración de marca por cliente (nombre, logotipo, colores, textos) en lugar de los valores de Restaurante Demo Uno.
- Plantilla de alta de cliente sin tocar código (hoy `tenants` hace el alta técnica; falta la de marca).
- Pruebas de fuga de identidad visual entre clientes.

### 3.5 Rediseño de la navegación

Sin cambios. Conviene decidirlo antes de partir `app.js` (3.7) y antes de reemplazar los usos de `innerHTML` pantalla por pantalla (3.6), para no reescribir dos veces.

### 3.6 Endurecimiento de la aplicación (nuevo)

Agrupa los hallazgos de Copilot que siguen abiertos o parciales. En orden de prioridad:

1. ~~**Actor y borrado** (hallazgo 3)~~ **Hecho en lo que tocaba**: el autor ya salía de la sesión; se añadió la prueba de que ningún `*_por` escapa a la sustitución. Queda para la etapa 2: reautenticación C2 en borrados y retención de archivos borrados.
2. ~~**Puerto de PostgreSQL** en `127.0.0.1`~~ **Hecho** (hallazgo 10).
3. ~~**XML seguro**~~ **Hecho** con `app/xml_seguro.py` (hallazgo 4).
4. **Validación por firma real** del archivo; ClamAV en el worker OCR (hallazgo 5).
5. **Cabeceras y CSP**: CSP en el Caddyfile y en un middleware local; `attachment` para lo que no sea PDF o imagen (hallazgo 7).
6. **Docs y OpenAPI** apagados en producción (hallazgo 14).
7. **Límites**: tasa de peticiones, carga de ventas por partes, CPU y memoria de los workers, cuota por cliente (hallazgo 6).
8. **Rutas relativas** de archivos y `filename` limpio (hallazgo 9).
9. **`innerHTML`**: revisión de los 84 usos, coordinada con el frente 5 (hallazgo 8).

Criterio de salida: cada punto con su prueba automática y las amenazas afectadas de `registro-amenazas.md` con su riesgo residual actualizado.

### 3.7 Calidad e ingeniería (nuevo)

1. ~~**Integración continua**~~ **Hecho** en `.github/workflows/ci.yml`: suite completa contra un data plane desechable con las 34 migraciones y RLS (`scripts/preparar_base_pruebas.py`) y gitleaks, que bloquean; `pip-audit` y `bandit` sólo informan hasta corregir lo existente. Falta `ruff` (la base de código no está formateada todavía) y Semgrep.
2. `requirements-dev.txt` separado y versiones con hash.
3. Un solo aplicador de migraciones en desarrollo y en servidor.
4. Pruebas nuevas: archivos maliciosos, carga (24 000 documentos por semana y 14 usuarios simultáneos, según `docs/cola-ocr.md`), cobertura y redondeo de dinero.
5. Logging JSON con ID de correlación; reemplazar los `except Exception` genéricos.
6. Partir `main.py`, `repository.py` y `app.js` en módulos (después de la integración y del rediseño de navegación).

### 3.8 Integridad de la base de datos (nuevo)

Sale de la revisión de base de datos (§2.3). En orden de prioridad:

1. ~~**Proteger la auditoría**~~ **Hecho** (migración 034 y `tests/test_auditoria_solo_anexado.py`). El borrado lógico de facturas pasa a la etapa 2.
2. **Identidad estable** (punto 3): una columna con el ID de identidad del plano de control al lado de cada `*_por`, llenada desde la sesión.
3. **Timeouts** de `tenant_runtime` (punto 16).
4. **Reglas financieras** (punto 8): primero una consulta que cuente cuántas filas actuales romperían cada regla; luego `CHECK`, triggers diferidos de sumas y `EXCLUDE`.
5. **Pruebas de la base** (punto 17): restricciones, cascadas y triggers.
6. **Rendimiento**: índices y `pg_trgm` guiados por `EXPLAIN` con volumen realista; particionado y retención cuando haga falta (puntos 10, 13 y 14).
7. **Menores**: `CHECK` de JSONB, transiciones de `estado_factura`, `es_demo` y siembra (puntos 7, 9, 11 y 12).

Criterio de salida: cada cambio con su prueba, y ninguna migración destructiva sin respaldo previo comprobado.

### Avance de la etapa 1 (2026-10-19)

Rama `claude/roadmap-audit-integration-2dcf8d`, montada sobre la del PR #2 (que ya está en `main`, etapa 0 hecha).

- Migración **034**: auditoría de sólo anexado y `RESTRICT` en correcciones. Comando nuevo `python -m app.plataforma.tenants migrar --clave <CLIENTE>` para aplicar migraciones a un cliente ya dado de alta (antes sólo se aplicaban en el alta). **Aplicada a GRUPO-DEMO y a GRUPO-PRUEBA-B** (respaldo previo de GRUPO-DEMO, snapshot 6a365126).
- XML y XLSX seguros, PostgreSQL de desarrollo sólo en `127.0.0.1`, prueba del autor sustituible.
- Integración continua lista; empieza a correr en cuanto la rama se suba a GitHub.
- Suite contra una base desechable: 174 pasan y 75 se omiten (Keycloak y plano de control). La única que falla, `test_plataforma_no_lee_politicas_globales_ni_borra_claves`, necesita el token de OpenBao que está en la otra copia de trabajo; no depende de estos cambios.

### Avance de la etapa 2 (2026-10-20)

Rama de integración `integracion/etapa2`: reúne el trabajo de los PR #3 y #9 a #17 ya fusionado y con la suite completa en verde, para entrar a `main` de una vez. Las filas de §2 describen el estado del 2026-10-19; esta tabla las actualiza.

| Punto del roadmap | Hecho | Queda |
|---|---|---|
| §3.1 / hallazgo 1: salir del modo abierto | `acceso_modo` es `seguro` por defecto y producción no arranca en modo abierto (D-028, PR #5). | Retirar por completo el modo abierto cuando el front ya no lo necesite en desarrollo. |
| §3.6.4 / hallazgo 5: firma de archivos y antivirus | Verificación por los primeros bytes en facturas, lotes, evidencias, catálogo y ventas; la extensión sale del contenido (PR #7). ClamAV obligatorio en el servidor, probado con EICAR (D-030). | Un PDF corrupto con firma válida sigue llegando al OCR. |
| §3.6.5 / hallazgo 7: cabeceras y CSP | CSP (`script-src 'self'`), `nosniff`, `X-Frame-Options`, `Referrer-Policy`; sólo PDF e imágenes en línea (PR #4). | `style-src` sin `unsafe-inline`: requiere sustituir los atributos `style` del front. |
| §3.6.6 / hallazgo 14: `/docs` | Apagado fuera de desarrollo con acceso abierto (PR #4). | — |
| §3.6.7 / hallazgo 6: tasa y recursos | Límite de peticiones por IP (429), lectura de archivos por partes, topes de memoria y CPU, contenedores sin capacidades y API de sólo lectura (PR #6, #16), cuotas por cliente de 10 000 documentos al día y 50 GB (D-030). | Workers sin salida a internet (necesita la red del servidor). |
| §3.6.8 / hallazgo 9: rutas y nombres | Rutas relativas al directorio del cliente y nombres limpios (PR #10). | Convertir las rutas absolutas ya guardadas (las raíces varían por entorno). |
| §3.6.9 / hallazgo 8: `innerHTML` | Revisados los 79 usos: todo texto de la base se escapa; prueba estática contra regresiones (PR #17). | — |
| §3.7.1 / hallazgo 15: escaneo en CI | `bandit` limpio y bloqueante; `pip-audit` bloqueante; XML revisa todo el contenido (PR #8, #12). | `ruff` y Semgrep. |
| §3.7.2: dependencias de desarrollo | `requirements-dev.txt` con herramientas fijadas (PR #8). | Versiones con hash. |
| §3.7.3: un solo aplicador de migraciones | `app/migraciones.py` para clientes, CI y desarrollo (PR #9). | — |
| §3.7.4: pruebas | Dinero sin `float` y redondeo, cobertura en CI (65 %, sin umbral), pruebas de restricciones de la base (PR #14, #15). | Pruebas de carga (24 000 documentos por semana y 14 usuarios: **necesitan un entorno de medición**). Piso de cobertura de 60 % fijado (D-030). |
| §3.7.5 / hallazgo 12: registro | ID de correlación por petición y JSON en servidor (PR #13). | Tablero de alertas y métricas de la cola. |
| §3.8.2: identidad estable | Migración 035: `<col>_por_id` copiado de la sesión por trigger, 29 columnas (D-029, PR #11). | Aplicarla a GRUPO-DEMO y GRUPO-PRUEBA-B con `tenants migrar`, con respaldo previo. |
| §3.8.3: topes de `tenant_runtime` | `statement_timeout` 120 s e `idle_in_transaction` 60 s (PR #11). | — |
| §3.8.4: reglas financieras | Revisado: periodos ya validados por `CHECK`. Se mantiene aprobar un desglose que no cuadra «verificando el total» (D-030): no habrá `CHECK` de totales. | `EXCLUDE` de periodos: falta definir la clave. |
| §3.8.5: pruebas de la base | 11 pruebas de restricciones (PR #15). | Triggers y cascadas más finos. |

**Pendientes que necesitan una decisión tuya**

- (Resueltas el 2026-10-20, D-030: ClamAV sí, piso de cobertura de 60 %, el desglose que no cuadra se mantiene, cuotas por defecto y retención de 5 años.)
- Borrado lógico de facturas: hoy sólo se borran (físicamente) documentos pendientes y las aprobadas no se pueden quitar. La **reautenticación C2 en borrados ya existe**: `DELETE /api/v1/facturas` y la cancelación o borrado de lotes son C2 en `politica.py`, el servidor exige autenticación de menos de 15 minutos y `acceso.js` la solicita; falta pedir un **motivo** (AS-09). La opción propuesta es una *anulación* de facturas aprobadas, con motivo, sin borrar el registro ni el archivo (5 años, D-030); está pendiente de tu elección.
- Archivar `codex/security-foundation`: la rama sigue en `origin`; borrarla o etiquetarla es tu decisión.

## 4. Orden de ejecución propuesto

| Etapa | Contenido | Por qué en este orden |
|-------|-----------|-----------------------|
| **0. Integrar** *(hecha salvo archivar el legado)* | 3.0: PR #2 fusionado en `main` (`f2dcf23`); pendiente archivar `codex/security-foundation`. | Sin esto, toda auditoría y todo cambio se hace sobre código viejo. |
| **1. Inmediato** (cambios chicos y de alto impacto) | 3.6 puntos 1 a 3 (actor y borrado, puerto 5432, `defusedxml`), 3.8 punto 1 (auditoría sin cascada y borrado lógico) y 3.7 punto 1 (integración continua). | Cierra el hueco confirmado del historial que se borra en cascada y deja una red de pruebas para lo que sigue. |
| **2. Antes de producción** | 3.6 puntos 4 a 7; 3.1 salir del modo abierto; 3.7 puntos 2 a 5; 3.8 puntos 2 a 5. | Son la condición para desplegar y para que el pentest valga la pena. |
| **3. Despliegue** | 3.1: VPS, bucket, guía de despliegue, SMTP real, red por cliente; luego el pentest externo. | Ya con la aplicación endurecida. |
| **4. Producto** | Frentes 2, 4 (marca y plantilla de alta) y 3 cuando llegue su definición. | Dependen del modelo de tenant ya listo y del modo seguro. |
| **5. Mediano plazo** | Frente 5 (navegación); 3.6 punto 9 (`innerHTML`); 3.7 punto 6 (partir módulos); 3.8 puntos 6 y 7; observabilidad. | Conviene hacerlos juntos para no reescribir dos veces la interfaz. |

## 5. Pendientes de decidir

- Si los 100 MB por archivo son el tope correcto, o si se baja para PDF e imágenes y se deja alto sólo para lotes.
- Plazo de retención del borrado lógico y quién puede recuperar o purgar.

Decididas el 2026-10-19:

- **Tolerancia en centavos del `CHECK` de totales:** queda flexible por ahora (parámetro ajustable, no fijo en el esquema) y se ajusta con datos reales una vez en producción.
- **Borrado de facturas con correcciones:** se **impide** (`ON DELETE RESTRICT` en `audit.correcciones`). Una factura con historial de correcciones no se borra.
- Si ClamAV entra ya o después del pentest (consume memoria; el equipo de desarrollo tiene poca).
- Las de la hoja anterior siguen en pie: modelo de llave física, VPS y región (Hetzner Ashburn o AWS mx-central-1), SMTP transaccional y nueva definición de reportes.
