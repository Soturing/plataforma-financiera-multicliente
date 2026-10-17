# Facturación IA — guía de trabajo

Plataforma financiera para restaurantes: carga de facturas → OCR → interpretación → revisión humana → factura final → analytics/Excel/PDF. Ya se ha operado en producción: **decisiones simples y salidas rápidas**. No sobre-ingenierizar.

Fuente de verdad documental: `README.md`, `docs/decisiones.md` (D-001…D-017) y `docs/roadmap-producto.md`. Este archivo es solo un resumen operativo; si algo contradice a esos documentos, mandan ellos.

## Stack
- Python + FastAPI (`app/main.py`), PostgreSQL 15+ (docker `compose.yaml`), front estático sin build (`app/static/`: `index.html`, `app.js`, `styles.css`).
- OCR local: PDF digital por capa de texto primero; PaddleOCR solo como respaldo (`app/ocr/`).
- Migraciones SQL versionadas en `db/migrations/` (001–027). Nueva migración = siguiente número, nunca editar las existentes.
- Tests: `tests/` (pytest) y `db/tests/001_pipeline_smoke.sql`.

## Comandos (PowerShell, Windows)
```powershell
py -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt
docker compose up -d
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
- Usuarios, roles, bloqueo por pago, multi-tenant: **diseñados, no implementados** (roadmap + `docs/seguridad/`). Ya no es una demo de salida rápida: se construye como producto real, así que el aislamiento fuerte por cliente (D-016) y las medidas de seguridad **sí se implementan**. Esa arquitectura conviene trabajarla en una sesión con Opus.
- El historial "rápido" del proyecto anterior no justifica atajos nuevos en seguridad.

## Entorno local (este worktree)
- Postgres propio en **puerto 5434** (`.env`, ignorado por git). Los contenedores `factaut-postgres-1` (5432) y `factaut-control-postgres-1` (5433) son de la versión anterior y pueden tener datos viejos (semanas 32–40 de 2026): **no tocarlos**.
- Se parte de base limpia. Si aparecen datos de las semanas 32–40 de 2026, son contaminación.
- pytest en Windows: usar `--basetemp "$env:TEMP\pt-fa"` (el temp por defecto da PermissionError).
- Si se añade una migración nueva, también hay que registrarla en `compose.yaml` (lista de `initdb.d`).
- Bugs de OCR: se reproducen con documentos reales que el usuario deja en una carpeta local ignorada por git; solo fixtures sintéticos/anonimizados llegan a `tests/`.

## Forma de trabajar
- Cualquier duda de negocio o de alcance: preguntar al usuario antes de implementar.
- Cambios pequeños y verificables; correr pytest antes de dar algo por terminado.
- Los reportes actuales se mantienen hasta recibir la nueva definición funcional (roadmap #3).
- Comunicación con el usuario en español.
