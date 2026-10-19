# Facturación IA — guía de trabajo

Plataforma financiera para restaurantes: carga de facturas → OCR → interpretación → revisión humana → factura final → analytics/Excel/PDF. Ya se ha operado en producción: **decisiones simples y salidas rápidas**. No sobre-ingenierizar.

Fuente de verdad documental: `README.md`, `docs/decisiones.md` (D-001…D-027) y `docs/roadmap-producto.md`. Este archivo es solo un resumen operativo; si algo contradice a esos documentos, mandan ellos.

## Stack
- Python + FastAPI (`app/main.py`), PostgreSQL 15+ (docker `compose.yaml`), front estático sin build (`app/static/`: `index.html`, `app.js`, `styles.css`).
- OCR local: PDF digital por capa de texto primero; PaddleOCR solo como respaldo (`app/ocr/`).
- Migraciones SQL versionadas en `db/migrations/` (001–034). Nueva migración = siguiente número, nunca editar las existentes. A un cliente ya dado de alta se le aplican con `python -m app.plataforma.tenants migrar --clave <CLIENTE>`.
- Tests: `tests/` (pytest) y `db/tests/001_pipeline_smoke.sql`. CI en `.github/workflows/ci.yml` (base desechable con `scripts/preparar_base_pruebas.py`).
- La auditoría (`audit.*`) es de sólo anexado (D-027): para limpiar datos de prueba, la conexión de `tests/apoyo_db.py` ya declara `audit.purga=on`.

## Versionado
- Versión del producto `MAYOR.MENOR.PARCHE` en el archivo `VERSION` (pre-MVP: `0.x.y`); historial en `CHANGELOG.md`; política y pasos en `docs/versionado.md`. Esta rama es la línea de desarrollo hasta el MVP (no se fusiona con las demás). Sacar versión: `python scripts/bump_version.py patch|minor|major`; el commit y la etiqueta `vX.Y.Z` los decide quien revisa.
- Toda función nueva o cambio visible debe quedar en la sección vigente de `CHANGELOG.md`.

## Comandos (PowerShell, Windows)
```powershell
py -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
docker compose up -d
docker compose --profile identidad up -d identidad correo-pruebas   # Keycloak :8180 y Mailpit :8025 (tests/identidad)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload   # http://127.0.0.1:8000
.\.venv\Scripts\python.exe -m pytest -q
```

## Reglas de dominio que no se rompen
- Separar evidencia / propuesta / dato final: `ocr.resultados`, `ai.interpretaciones`, `core.facturas_finales` (D-002).
- La IA devuelve estructura validada; **nunca SQL libre** (D-003). Validaciones matemáticas, fiscales y de duplicidad viven en código y PostgreSQL.
- Toda factura pasa por revisión humana (D-007). Solo lo aprobado alimenta `analytics.movimientos_gasto`.
- Excel consume solo vistas estables de `analytics` (D-006).
- Nueve categorías fijas de gasto (D-017, `docs/categorias-gastos.md`); **no existen centros de costo**. Fijos y Nómina = gasto fijo; el resto = costo variable. Nómina (captura manual semanal) y Comisiones (proyección + cierre real mensual) no se capturan con facturas; los proveedores FIJOS requieren alta previa en la lista de gastos fijos.
- **Selector de sucursal:** con una sucursal seleccionada, toda pantalla, tabla, reporte y exportación muestra solo esa sucursal. "Consolidado" muestra las sucursales a las que el usuario tiene permiso (hoy todas, hasta que existan usuarios y permisos); nunca cifras de sucursales fuera de ese alcance. Aplica a todo lo nuevo.
- Cada gasto pertenece a una sola sucursal; `POR-ASIGNAR` bloquea la aprobación.
- Gastos `FIJOS` se periodifican por semanas ISO con ≥4 días en el periodo; el residuo de centavos va a la última semana.
- Editar una factura aprobada crea nueva versión, audita y reemplaza el movimiento vigente sin duplicar.
- Aprendizaje (alias, clasificación, periodicidad) solo si el capturista lo marca explícitamente; queda auditado.
- Reportes PDF deterministas, sin IA.

## Seguridad y datos
- **Nunca versionar datos, entregables ni documentos reales de clientes** (`docs/seguridad/politica-repositorio.md`, hook `.githooks/pre-commit`, `scripts/check_repo_safety.ps1`). Usar solo datos sintéticos.
- No imprimir ni commitear secretos; `.env` está fuera de git.
- Usuarios, roles y multi-tenant: **en construcción** según `docs/seguridad/plan-implementacion.md` (D-018 a D-024). Fases 1–7 hechas en local (falta ejecutar el despliegue: `docs/seguridad/despliegue-servidor.md`) (`app/seguridad/`, `db/control/`, `app/plataforma/`); el acceso es seguro por defecto (D-028); el modo abierto (D-022) es sólo una opción de desarrollo que se escribe a propósito en `.env` (`FACTURAS_ACCESO_MODO=abierto`). **Toda ruta nueva debe clasificarse en `app/seguridad/politica.py`** (módulo, acción, nivel y `sucursal_param`) o se deniega y fallan las pruebas. `codex/security-foundation` es legado y no se reutiliza. Bloqueo por pago: diseñado, no implementado. Ya no es una demo de salida rápida: el aislamiento fuerte por cliente (D-016) y las medidas de seguridad **sí se implementan**. Esa arquitectura conviene trabajarla en una sesión con Opus.
- El historial "rápido" del proyecto anterior no justifica atajos nuevos en seguridad.

## Entorno local (este worktree)
- La app que el usuario revisa corre en **http://127.0.0.1:8010** desde este worktree con `python -m app.plataforma.tenants servir --clave GRUPO-DEMO` (data plane propio en 5440, D-024). El puerto 8000 es legado y está apagado; no volver a levantarlo. La base 5434 es de `migrate-legacy`: no tocarla.
- Plano de control en 5436 (`control_app`), Keycloak en 8180, Mailpit en 8025, OpenBao en 8200 y destino de respaldos en 8090 (perfil `identidad`). Cliente ficticio de pruebas: `GRUPO-PRUEBA-B` (5441).
- **OpenBao queda sellado tras cada reinicio:** antes de `tenants servir` o de las pruebas, ejecutar `python -m app.plataforma.secretos abrir --desde-archivo`. Las contraseñas de las bases de los clientes están en OpenBao, no en `config/tenants/private/`.
- Pruebas: `python -m app.plataforma.tenants pruebas --clave GRUPO-DEMO -q --basetemp "$env:TEMP\pt-fa"` (app con RLS como `tenant_runtime`). Toda conexión a la base de negocio pasa por `app.database.conectar`; en pruebas, por `tests/apoyo_db.conexion_pruebas`. Toda tabla nueva necesita política RLS (la verificación de `tenants` lo exige).
- Postgres propio en **puerto 5434** (`.env`, ignorado por git). Los contenedores `factaut-postgres-1` (5432) y `factaut-control-postgres-1` (5433) son de la versión anterior y pueden tener datos viejos (semanas 32–40 de 2026): **no tocarlos**.
- Se parte de base limpia. Si aparecen datos de las semanas 32–40 de 2026, son contaminación.
- pytest en Windows: usar `--basetemp "$env:TEMP\pt-fa"` (el temp por defecto da PermissionError).
- Una migración nueva sólo necesita su archivo en `db/migrations/`: el único aplicador es `app/migraciones.py` (`python -m app.migraciones aplicar --url ...`; en clientes, `tenants migrar`). El `compose.yaml` ya no monta migraciones.
- Bugs de OCR: se reproducen con documentos reales que el usuario deja en una carpeta local ignorada por git; solo fixtures sintéticos/anonimizados llegan a `tests/`.

## Forma de trabajar
- Cualquier duda de negocio o de alcance: preguntar al usuario antes de implementar.
- Cambios pequeños y verificables; correr pytest antes de dar algo por terminado.
- Los reportes actuales se mantienen hasta recibir la nueva definición funcional (roadmap #3).
- Comunicación con el usuario en español.
