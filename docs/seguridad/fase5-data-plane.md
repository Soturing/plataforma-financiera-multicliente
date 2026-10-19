# Fase 5 — Data plane por cliente y RLS

Estado: implementado (2026-10-18). `GRUPO-DEMO` ya corre sobre su propio data plane en el 8010. Decisiones: D-016, D-019, D-024.

## 1. Modelo

```text
Tenant = administración (cliente de la consultora)  →  su propio stack
   └── Restaurantes  →  Sucursales                  →  misma base, estratificada
```

- **Entre clientes:** stacks separados. Cada cliente tiene su contenedor PostgreSQL, volumen, red, credenciales y almacenamiento de archivos. El backend de un cliente no tiene credenciales de otro.
- **Dentro de un cliente:** restaurantes y sucursales en la misma base. El alcance de cada persona se asigna por **restaurante completo** o por **sucursal** (tablas pivote `control.asignacion_restaurantes` y `control.asignacion_sucursales`), y la base lo aplica con RLS.

## 2. Qué hay

| Pieza | Archivo |
|---|---|
| Restaurantes formales (`catalog.restaurantes`) y sucursal → restaurante | `db/migrations/032_restaurantes.sql` |
| Identidad del tenant en la base, RLS forzado por tenant y por sucursal en todas las tablas, cuenta `tenant_runtime` sin privilegios | `db/migrations/033_rls_tenant_sucursal.sql` |
| Alcance por restaurante o sucursal en el plano de control | `db/control/002_restaurantes_pivote.sql` |
| Plantilla del stack por cliente | `deploy/tenant/compose.yaml` |
| Alta, servicio, verificación y pruebas por cliente | `app/plataforma/tenants.py` |
| Conexión que declara tenant y alcance en cada conexión | `app/database.py` (`conectar`, `rls_verificado`) |

### Cómo filtra la base

Cada conexión declara `app.tenant` (clave del cliente) y `app.sucursales` (`*` o lista de UUID).

| Tablas | Política |
|---|---|
| Con sucursal propia (facturas, ventas, nómina, comisiones, comprobantes, lotes…) | tenant correcto **y** sucursal dentro del alcance |
| Dependientes de una factura (OCR, interpretaciones, validaciones, revisiones…) | tenant correcto **y** la factura es visible |
| Catálogos del grupo (proveedores, categorías…) | tenant correcto |
| `audit.*` del negocio | la app sólo anexa (salvo confirmar la sucursal inferida) |

Sin `app.tenant`, o con el de otro cliente, la conexión **no ve ni escribe nada**. `FORCE ROW LEVEL SECURITY` aplica también a la propietaria, así que las vistas de `analytics` quedan filtradas igual que las tablas.

### Lo que cambió en la app

- Con RLS verificado en la base, los **consolidados** de una persona con sucursales limitadas ya no se bloquean: muestran sólo sus sucursales, como pide CLAUDE.md. Abrir por ID un documento de otra sucursal devuelve 404.
- Si la app se conecta a una base sin RLS efectivo (p. ej., la 5434 compartida), lo detecta y sigue bloqueando los consolidados.
- La cookie de sesión lleva el nombre del cliente y una sesión queda atada a su cliente. Presentarla en otro genera la alerta `INTENTO_ENTRE_TENANTS`.
- La pantalla de invitación permite elegir restaurantes completos o sucursales sueltas.

## 3. Clientes dados de alta

| Cliente | Base | App | Origen |
|---|---|---|---|
| `GRUPO-DEMO` | `127.0.0.1:5440` (proyecto Docker `fa-grupo-demo`) | 8010 | Copia de la base 5434 y de sus archivos (51 rutas reescritas). La 5434 queda intacta para `migrate-legacy`. |
| `GRUPO-PRUEBA-B` | `127.0.0.1:5441` (`fa-grupo-prueba-b`) | 8012 (no se sirve) | Ficticio, creado desde cero, sólo para pruebas de aislamiento |

Credenciales: `config/tenants/private/<CLAVE>.env` (ignorado por git).

## 4. Comandos

```powershell
# Alta de un cliente nuevo (aplica migraciones, verifica aislamiento y sólo entonces lo registra)
.\.venv\Scripts\python.exe -m app.plataforma.tenants alta --clave GRUPO-X --nombre "Grupo X" --puerto-db 5442 --puerto-app 8014 `
    --restaurante "REST-1:Restaurante 1" --sucursal "CENTRO:Centro:REST-1"

# Servir un cliente (así corre hoy el 8010)
.\.venv\Scripts\python.exe -m app.plataforma.tenants servir --clave GRUPO-DEMO

# Verificar aislamiento
.\.venv\Scripts\python.exe -m app.plataforma.tenants verificar --clave GRUPO-DEMO

# Pruebas contra el data plane de un cliente (app con RLS; preparación de datos como propietaria)
.\.venv\Scripts\python.exe -m app.plataforma.tenants pruebas --clave GRUPO-DEMO -q --basetemp "$env:TEMP\pt-fa"
```

## 5. Resultados

- `tenants pruebas --clave GRUPO-DEMO`: **221 pasan, 1 se omite**. Toda la app corre como `tenant_runtime` con RLS forzado.
- `tests/seguridad/test_aislamiento_tenants.py` (11): credenciales cruzadas rechazadas, backend con tenant equivocado sin filas, vistas filtradas, alcance de sucursal en tablas dependientes, escritura fuera de alcance rechazada por la política, auditoría de sólo anexado y consolidado por la app limitado a la sucursal asignada.
- Las pruebas antiguas que preparaban datos con conexiones directas usan ahora `tests/apoyo_db.py`.

## 6. Pendiente

- **Backend en contenedor por cliente:** en desarrollo corre en el equipo (`tenants servir`). La imagen Docker del backend y los workers se arma en la fase 7 (despliegue); aquí no se construyó.
- **Archivos:** cada cliente ya tiene su carpeta propia (`data/tenants/<CLAVE>/uploads`); cifrado con clave por cliente y almacenamiento de objetos, en la fase 7.
- **Semillas de demo:** las migraciones 007/009/012 siembran sucursales de demo; en clientes nuevos quedan inactivas. Conviene separar esquema y semillas.
- **Keycloak y varios clientes:** el cliente OIDC sólo acepta el callback del 8010. Cada cliente nuevo necesita su URL de regreso (en producción, su subdominio) registrada en Keycloak.
- **Consolidado entre clientes del director:** APIs internas de sólo lectura con métricas agregadas (arquitectura-aislamiento §12), todavía no construido.
- **`audit.documentos_eliminados`** conserva la ruta original del archivo como evidencia (sólo anexado).
