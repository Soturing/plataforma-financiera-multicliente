# Versionado

El producto usa versionado semántico **MAYOR.MENOR.PARCHE** (por ejemplo `0.1.0`). Esta línea de desarrollo
(`claude/migrate-legacy-project-d73050`) es la que llega al MVP; no se fusiona con las demás ramas.

- **Fuente única:** el archivo `VERSION` de la raíz. `app/version.py` lo lee; la API lo expone en
  `GET /health` y en la documentación (`/docs`), y el menú lateral lo muestra.
- **Antes del MVP la versión empieza en 0:** `0.MENOR.PARCHE`. El 1.0.0 será el MVP.
- **PARCHE** (`0.1.1`): correcciones que no cambian lo que el usuario puede hacer.
- **MENOR** (`0.2.0`): funciones nuevas o cambios visibles; también cambios de base de datos.
- **MAYOR** (`1.0.0`, `2.0.0`): ruptura de compatibilidad o hitos de producto.
- Cada versión cita en `CHANGELOG.md` las migraciones nuevas (las bases existentes se actualizan a mano).

## Cómo sacar una versión

```powershell
python scripts/bump_version.py patch   # o minor / major; --dry-run solo muestra el número
# completar CHANGELOG.md, revisar, y luego los comandos que imprime el script:
git add -A; git commit -m "chore: versión X.Y.Z"; git tag -a vX.Y.Z -m "Versión X.Y.Z"
```

El script no hace commit ni etiqueta: eso lo decide quien revisa. Las etiquetas llevan `v` (`v0.1.0`).
La migración de datos de la producción antigua se planeará como una versión propia antes del MVP.
