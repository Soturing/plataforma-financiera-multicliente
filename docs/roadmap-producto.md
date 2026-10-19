# Hoja de ruta del producto

Actualizada: 2026-10-19. Integra tres fuentes:

- la hoja de ruta anterior (frentes 1 a 5);
- el plan de seguridad por fases ([seguridad/plan-implementacion.md](seguridad/plan-implementacion.md), fases 1 a 7);
- la auditoría estática de GitHub Copilot del 2026-10-19 (16 hallazgos de seguridad y 11 de arquitectura).

> **Importante sobre la auditoría.** Copilot revisó la base saneada (`main`, commit `e794699`), que no tiene nada del trabajo de octubre. Cada hallazgo se volvió a comprobar contra la rama más avanzada, `claude/roadmap-usuarios-seguridad-8e43ba` (PR #2, que ya contiene `migrate-legacy`). La columna «Estado real» de §2 refleja esa rama, no `main`.

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
| 0 | **Integración de ramas** *(nuevo, bloquea todo lo demás)* | Pendiente. Ver §3.0. | — |

## 2. Conciliación de la auditoría de Copilot

Estados: **Resuelto** (ya está en la rama de seguridad), **Parcial** (resuelto en parte o sólo en el servidor), **Abierto** (sin cambios).

### 2.1 Seguridad

| # | Sev. | Hallazgo de Copilot | Estado real | Lo que falta | Frente |
|---|------|---------------------|-------------|--------------|--------|
| 1 | Crítica | Sin autenticación ni autorización | **Parcial.** Keycloak, sesiones en el plano de control y política por ruta (`app/seguridad/politica.py`) están hechos, pero `acceso_modo` vale `"abierto"` por defecto (`app/config.py:32`): sin sesión la app sigue respondiendo como antes. | Cambiar el valor por defecto a `"seguro"` y retirar el modo abierto antes de producción. | 1 |
| 2 | Crítica | Sin aislamiento multicliente | **Resuelto.** Base, archivos y workers propios por cliente; `tenant_id` y RLS con `FORCE` (migración 033); prueba con dos tenants. | Llevar las pruebas de fuga a la integración continua (§3.7). Red propia por cliente entre proxy y app (ya pendiente). | 4 |
| 3 | Alta | Acciones destructivas con identidad falsificable | **Parcial; hueco confirmado.** Existe `actor_o()` para tomar el autor de la sesión, pero `DELETE /api/v1/facturas` y el descarte de duplicados todavía usan el valor del navegador (`data.eliminado_por` en `app/main.py:434` y `:1273`, `data.descartado_por` en `:343`). Además borran archivos físicos. | Usar el actor de la sesión, quitar esos campos de la petición, borrado lógico con retención y reautenticación (nivel C2). | 6 |
| 4 | Alta | XML sin protección XXE / *billion laughs* | **Abierto.** `xml.etree` en `app/text_processing.py` y `app/provider_catalog.py`. | `defusedxml` y tope al tamaño descomprimido del XLSX (bomba zip). | 6 |
| 5 | Alta | Validación de archivos sólo por `Content-Type` | **Abierto.** `app/storage.py` confía en el tipo y la extensión que manda el cliente. | Comprobar la firma real del archivo; antivirus (ClamAV) en el worker. | 6 |
| 6 | Alta | Sin límite de tasa ni de recursos | **Parcial.** Lo del `Popen` por factura ya se resolvió: ahora hay una cola en PostgreSQL con workers permanentes (030). Límite unificado en 100 MB (`config.py` y `.env.example` coinciden). Siguen abiertos: el límite de peticiones, la carga de ventas que lee el archivo entero en memoria (`main.py:823` y `:1118`) y los límites de CPU y memoria de los workers. | Límite de peticiones en Caddy o con `slowapi`, ventas leídas por partes, `cpus`/`mem_limit` en el compose del servidor, cuota por cliente. Revisar si 100 MB es el tope correcto. | 6 |
| 7 | Media | Faltan cabeceras; archivos servidos `inline` | **Parcial.** El Caddyfile del servidor ya pone HSTS, `nosniff`, `X-Frame-Options`, `Referrer-Policy` y `Permissions-Policy`. Falta CSP; en local no hay cabeceras; los archivos subidos se siguen sirviendo `inline` (`main.py:333`, `:485`, `:656`). | CSP estricta, middleware de cabeceras en la app y `attachment` para todo lo que no sea PDF o imagen. | 6 |
| 8 | Media | Uso extenso de `innerHTML` | **Abierto, y peor:** 84 usos en `app.js` (148 KB). | Revisar cada uso, pasar a `textContent`, ESLint con regla de seguridad. CSP como red de seguridad. | 6 / 7 |
| 9 | Media | Rutas absolutas en la base; nombre original en `Content-Disposition` | **Abierto.** | Guardar rutas relativas al directorio del cliente y limpiar `filename`. | 6 |
| 10 | Media | Sin cifrado en reposo; PostgreSQL en `0.0.0.0:5432` | **Parcial.** gocryptfs por cliente y respaldos cifrados en S3 con Object Lock (D-025, D-026). Pero el `compose.yaml` de desarrollo sigue publicando `${POSTGRES_PORT:-5432}:5432` en todas las interfaces (línea 9). | Publicarlo sólo en `127.0.0.1`. TLS hacia la base si alguna vez sale del host. | 6 |
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

## 3. Detalle de los frentes

### 3.0 Integración de ramas (nuevo; bloquea el resto)

Hoy hay tres líneas sin fusionar: `main` (base saneada), `codex/security-foundation` (legado, **no se reutiliza**) y `claude/roadmap-usuarios-seguridad-8e43ba` (PR #2, que ya incluye `migrate-legacy`). La auditoría encontró todo esto «sin implementar» precisamente porque `main` está atrasada.

- Revisar y fusionar el PR #2 en `main`, para que cualquier auditoría futura vea el código real.
- Archivar `codex/security-foundation` con una nota en `decisiones.md` y cerrar los worktrees viejos.
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

1. **Actor y borrado** (hallazgo 3): `actor_o()` en todos los endpoints que reciben `eliminado_por`, `descartado_por` o campos parecidos; quitar esos campos de los modelos de petición; borrado lógico de facturas y archivos con un plazo de retención; reautenticación C2. Agregar una prueba que falle si una ruta acepta el autor desde el cuerpo de la petición.
2. **Puerto de PostgreSQL** en `127.0.0.1` en `compose.yaml` (hallazgo 10). Es un cambio de una línea.
3. **XML seguro** con `defusedxml` y tope de descompresión del XLSX (hallazgo 4).
4. **Validación por firma real** del archivo; ClamAV en el worker OCR (hallazgo 5).
5. **Cabeceras y CSP**: CSP en el Caddyfile y en un middleware local; `attachment` para lo que no sea PDF o imagen (hallazgo 7).
6. **Docs y OpenAPI** apagados en producción (hallazgo 14).
7. **Límites**: tasa de peticiones, carga de ventas por partes, CPU y memoria de los workers, cuota por cliente (hallazgo 6).
8. **Rutas relativas** de archivos y `filename` limpio (hallazgo 9).
9. **`innerHTML`**: revisión de los 84 usos, coordinada con el frente 5 (hallazgo 8).

Criterio de salida: cada punto con su prueba automática y las amenazas afectadas de `registro-amenazas.md` con su riesgo residual actualizado.

### 3.7 Calidad e ingeniería (nuevo)

1. **Integración continua** en GitHub Actions: `pytest` (incluidas las pruebas de aislamiento con dos tenants), `ruff`, `pip-audit`, `bandit`, `gitleaks`. Semgrep si se puede.
2. `requirements-dev.txt` separado y versiones con hash.
3. Un solo aplicador de migraciones en desarrollo y en servidor.
4. Pruebas nuevas: archivos maliciosos, carga (24 000 documentos por semana y 14 usuarios simultáneos, según `docs/cola-ocr.md`), cobertura y redondeo de dinero.
5. Logging JSON con ID de correlación; reemplazar los `except Exception` genéricos.
6. Partir `main.py`, `repository.py` y `app.js` en módulos (después de la integración y del rediseño de navegación).

## 4. Orden de ejecución propuesto

| Etapa | Contenido | Por qué en este orden |
|-------|-----------|-----------------------|
| **0. Integrar** | 3.0: fusionar el PR #2 en `main` y archivar el legado. | Sin esto, toda auditoría y todo cambio se hace sobre código viejo. |
| **1. Inmediato** (cambios chicos y de alto impacto) | 3.6 puntos 1 a 3 (actor y borrado, puerto 5432, `defusedxml`) y 3.7 punto 1 (integración continua). | Cierra el único hueco confirmado de identidad y deja una red de pruebas para lo que sigue. |
| **2. Antes de producción** | 3.6 puntos 4 a 7; 3.1 salir del modo abierto; 3.7 puntos 2 a 5. | Son la condición para desplegar y para que el pentest valga la pena. |
| **3. Despliegue** | 3.1: VPS, bucket, guía de despliegue, SMTP real, red por cliente; luego el pentest externo. | Ya con la aplicación endurecida. |
| **4. Producto** | Frentes 2, 4 (marca y plantilla de alta) y 3 cuando llegue su definición. | Dependen del modelo de tenant ya listo y del modo seguro. |
| **5. Mediano plazo** | Frente 5 (navegación); 3.6 punto 9 (`innerHTML`); 3.7 punto 6 (partir módulos); observabilidad. | Conviene hacerlos juntos para no reescribir dos veces la interfaz. |

## 5. Pendientes de decidir

- Si los 100 MB por archivo son el tope correcto, o si se baja para PDF e imágenes y se deja alto sólo para lotes.
- Plazo de retención del borrado lógico y quién puede recuperar o purgar.
- Si ClamAV entra ya o después del pentest (consume memoria; el equipo de desarrollo tiene poca).
- Las de la hoja anterior siguen en pie: modelo de llave física, VPS y región (Hetzner Ashburn o AWS mx-central-1), SMTP transaccional y nueva definición de reportes.
