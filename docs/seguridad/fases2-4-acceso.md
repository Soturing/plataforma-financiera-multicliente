# Fases 2 a 4 — Plano de control, sesiones y autorización

Estado: implementado y visible en `http://127.0.0.1:8010/#/` (2026-10-18), en **modo abierto** (D-022). Plan: [plan-implementacion.md](plan-implementacion.md).

## 1. Qué hay ahora en la aplicación

| Dónde | Qué se ve |
|---|---|
| Barra superior | "Modo abierto" e **Iniciar sesión**. Con sesión: nombre, rol, cliente, 🔑 si se entró con llave física, **Cambiar rol** y **Salir**. En pantallas angostas, versión compacta. |
| Menú → **Usuarios y accesos** (`#/accesos`) | Personas con acceso, sus roles, cliente y sucursales; **Invitar persona**; **Suspender** y **Cerrar sesiones** con motivo; bitácora de seguridad con verificación de la cadena ("Cadena íntegra · N eventos"). Sin sesión, pide iniciar sesión. |
| Menú lateral | Con sesión, sólo muestra los módulos que permite el rol (p. ej., el Administrador de seguridad sólo ve Inicio y Usuarios y accesos). |
| Ventana "¿Con qué rol vas a trabajar?" | Aparece al entrar si la persona tiene más de un rol. Cambiar de rol después pide confirmar identidad (D-020). |

En modo abierto, quien no inicia sesión sigue usando la app como antes (campo "Operador" libre). Quien inicia sesión opera con sus permisos y su nombre real se guarda como autor.

## 2. Cómo está construido

```text
Navegador ── cookie HttpOnly fa_sesion (token aleatorio) ──► App 8010 (FastAPI)
                                                             │
                     autorizar_ruta (dependencia global) ────┤ 1. clasificación de la ruta (politica.RUTAS)
                                                             │ 2. sesión vigente, identidad y asignación activas
                                                             │ 3. rol × módulo × acción (+ permisos condicionados)
                                                             │ 4. sucursal dentro del alcance
                                                             │ 5. autenticación reciente para C2 (15 min) / C3 (5 min)
                                                             │ 6. auditoría de rechazos y de acciones C1+
                                                             │ 7. autor = identidad de la sesión
                                                             ▼
                          Plano de control (PostgreSQL 5436)     Keycloak 8180 (OIDC + PKCE, servidor)
```

| Pieza | Archivo |
|---|---|
| Esquema del plano de control, cuenta `control_app`, bitácora encadenada | `db/control/` |
| Matriz de permisos y clasificación de las 86 rutas | `app/seguridad/politica.py` |
| Sesiones, tiempos por rol, revocación | `app/seguridad/sesiones.py` |
| OIDC del lado del servidor | `app/seguridad/oidc.py` |
| Autorización global y autor de la operación | `app/seguridad/autorizacion.py` |
| Rutas `/auth/*` y `/api/v1/seguridad/*` | `app/seguridad/api.py` |
| Administración de usuarios en Keycloak (cuenta de servicio `facturas-control`) | `app/seguridad/keycloak_admin.py` |
| Instalador (cliente, primer director, reenvío de invitación) | `app/seguridad/instalar.py` |
| Interfaz | `app/static/acceso.js`, cambios menores en `app.js`, `index.html`, `styles.css` |

### Reglas que se cumplen y se prueban

- Toda ruta está clasificada; una ruta nueva sin clasificar se deniega y rompe las pruebas.
- Toda ruta que recibe `sucursal_clave` declara el filtro de sucursal.
- Retirar una asignación, suspender a la persona o cerrar sus sesiones invalida la sesión **en la siguiente petición**.
- Reutilizar una sesión revocada genera un evento de alerta.
- Los roles privilegiados sólo se usan con sesión iniciada con llave física.
- Una persona con dos roles opera con uno a la vez; cambiar exige reautenticación.
- El autor de cada operación sale de la sesión: el servidor ignora `revisada_por`, `creada_por`, etc. enviados por el navegador.
- La bitácora es de sólo anexado: la app no puede modificarla ni borrarla, y la verificación detecta alteraciones hechas por el propietario de la base.
- El destino después de iniciar sesión sólo puede ser una ruta interna; el `state` del inicio de sesión es de un solo uso y caduca a los 10 minutos.

Pruebas: `tests/seguridad/` (42) y `tests/identidad/` (14). La de punta a punta registra una passkey real de software, entra por la app, se reautentica y sale.

## 3. Supuestos que tomé (revisar)

1. **Nómina:** el capturista puede capturarla (`NOMINA: OPERAR`). La matriz no lo decía y D-017 la trata como captura semanal operativa.
2. **Consolidados con sucursales limitadas:** si la asignación tiene sólo algunas sucursales, las vistas consolidadas se **deniegan** y piden elegir una sucursal. La regla de CLAUDE.md ("Consolidado muestra las sucursales permitidas") requiere filtrar dentro de cada consulta; queda para la fase 5 junto con RLS.
3. **Consulta por identificador:** abrir un documento por su ID todavía no comprueba la sucursal del documento (sí el rol y el módulo). Se cierra en la fase 5 con RLS por sucursal.
4. **Director inicial:** se creó como `director@consultora.test` porque no tenía tu correo para esto. Ver §4.

## 4. Guía para tu revisión

### 4.1 Ver la interfaz sin iniciar sesión

Abre `http://127.0.0.1:8010/#/`: barra con "Modo abierto · Iniciar sesión" y el nuevo menú "Usuarios y accesos".

### 4.2 Registrar tu llave y entrar como director

1. Abre Mailpit: `http://localhost:8025`. Hay un correo para `director@consultora.test`.
2. Abre el enlace del correo más reciente (se reenvió a las ~4:20 del 18 de octubre; vale 24 h). Si caducó:

   ```powershell
   .\.venv\Scripts\python.exe -m app.seguridad.instalar reenviar --correo director@consultora.test
   ```

3. Registra una **llave física**: una llave FIDO2, o tu teléfono con "Usar un teléfono o tableta" (código QR) en Chrome o Edge. Windows Hello no sirve para este rol: la política de roles globales exige un autenticador externo.
4. En `http://127.0.0.1:8010/#/` pulsa **Iniciar sesión**, escribe `director@consultora.test` y usa la llave.
5. Elige "Director" o "Administrador de seguridad" y ve a **Usuarios y accesos**.

Para invitar a un capturista de prueba, usa un correo cualquiera: el correo llega a Mailpit y la persona registra una passkey normal (Windows Hello sirve).

### 4.3 Activar el modo seguro (cuando ya tengas tu llave)

En `.env`: `FACTURAS_ACCESO_MODO=seguro` y reinicia la app de la pestaña "app 8010". Desde entonces todo exige sesión.

### 4.4 Contenedores y procesos

```powershell
docker compose --profile identidad up -d identidad correo-pruebas control-postgres
```

Keycloak usa ~1 GB de RAM y tarda varios minutos en arrancar en este equipo.

- El 8010 corre en la pestaña "app 8010" del panel de Terminal, desde esta rama.
- Para volver a servir `migrate-legacy` en el 8010: detén esa pestaña (Ctrl-C) y, desde `.claude\worktrees\migrate-legacy-project-d73050`, ejecuta `.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8010`.
- El puerto 8000 (copia legacy) quedó apagado. Sus dos tareas programadas ("Facturacion IA" y "Facturacion IA Demo") están **desactivadas**, no borradas; se reactivan con `Enable-ScheduledTask`.

## 5. Lo que falta

- **Fase 5 (data plane por cliente + RLS):** no la empecé. La base de negocio (5434) es compartida con `migrate-legacy`: activar `FORCE ROW LEVEL SECURITY` y una cuenta sin propiedad rompería esa línea si se vuelve a ejecutar. Hace falta decidir si esta rama usa su propia base (D-023).
- **Fase 6:** ya hay invitación, suspensión y cierre de sesiones. Faltan dispositivo perdido, recuperación asistida con espera de 24 h, baja completa, inactividad, y obligar a registrar una passkey nueva tras usar un código de recuperación.
- **Fase 7:** secretos, claves por cliente, respaldos y pruebas de penetración.
