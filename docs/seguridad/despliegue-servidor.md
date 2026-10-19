# Despliegue en servidor (fase 7, parte 2)

Estado: preparado y probado en local (2026-10-18). Falta contratar el VPS y el bucket y ejecutar esta guía. Decisiones: D-016, D-019, D-024, D-025, D-026.

## 1. Arquitectura en el servidor

```text
Internet ──443──► Caddy (TLS automático)
                    ├── accesos.<dominio>      → Keycloak (sólo pantalla de acceso; /admin bloqueado)
                    ├── grupo-demo.<dominio>   → app de GRUPO-DEMO   ─┐
                    └── otro-grupo.<dominio>   → app de OTRO-GRUPO   ─┤
                                                                      │ red facturas_control
          OpenBao · base de control · Keycloak (sólo 127.0.0.1 / red interna)
                                                                      │
   Por cliente (proyecto Docker fa-<cliente>):                        │
     app + workers  ◄── secretos de OpenBao al arrancar ──────────────┘
       │  red propia (dataplane) → PostgreSQL del cliente
       └─ /datos/uploads = vista descifrada de gocryptfs ◄── /srv/facturas/<CLIENTE>/archivos.cifrados
   Respaldos diarios (restic) ──► bucket S3 con Object Lock, un prefijo y una credencial por cliente
```

- **Una imagen para todos** (`deploy/app/Dockerfile`), un stack por cliente (`deploy/tenant/compose.yaml`, perfil `servidor`).
- **Ningún secreto en archivos del servidor**, salvo la credencial de arranque de cada cliente. El contenedor la usa para pedir a OpenBao su conexión y los secretos compartidos, y la borra antes de lanzar la app (`app/plataforma/arranque.py`). Corre sin privilegios (uid 10001).
- **Archivos cifrados en reposo** con gocryptfs por cliente. La contraseña sólo existe envuelta por la clave `<CLIENTE>-datos` de OpenBao y se entrega por la entrada estándar al montar (`app/plataforma/archivos.py`).
- **Tras un reinicio**, una persona ejecuta `deploy/servidor/arrancar.sh`: abre OpenBao con 2 llaves, monta los archivos y levanta cada cliente. Hasta entonces la app no arranca.

## 2. Recomendación de proveedor

### Tamaño

| Componente | Memoria aproximada |
|---|---|
| Keycloak | 1.2 GB |
| OpenBao, Caddy, 2 PostgreSQL de control | 0.6 GB |
| Por cliente: PostgreSQL + app | 0.7 GB |
| Por cliente: 1 worker OCR (PaddleOCR) | 1.5–2 GB |

Con 1–2 clientes: **mínimo 8 GB y 4 vCPU; recomendado 16 GB y 4–8 vCPU** (el OCR consume mucha CPU), 160 GB NVMe y Ubuntu 24.04 LTS.

### VPS

| Opción | Cuándo | Notas |
|---|---|---|
| **Hetzner Cloud, Ashburn (EE. UU. Este)** — recomendada | Si no hay obligación contractual de que los datos estén en México | La mejor relación precio/memoria. Sus precios en EE. UU. son bastante más altos que en Europa y subieron en 2026: confirmar el precio vigente en su consola antes de contratar |
| DigitalOcean (Nueva York o San Francisco) | Si se prefiere soporte y panel más sencillos | Más caro por GB de memoria |
| **AWS, región México (mx-central-1)** | Si un cliente exige que los datos permanezcan en México | Región disponible desde 2025; la opción más cara y con más configuración |

### Almacenamiento de respaldos

**Backblaze B2 con Object Lock (modo *compliance*)** — recomendado:
- **Proveedor distinto al del VPS:** si se pierde o compromete la cuenta del servidor, los respaldos siguen a salvo.
- Admite Object Lock por su API compatible con S3.
- Precio publicado de unos 6.95 USD por TB al mes, con descarga gratuita hasta 3 veces lo almacenado. Con el volumen actual (menos de 50 GB) es menos de 1 USD al mes. Conviene confirmarlo en su página oficial.
- Configuración: **un bucket con versiones y Object Lock**, retención por defecto de 30 días en modo *compliance*, reglas de ciclo de vida para 30 diarios, 12 mensuales y 7 anuales, y **una application key por cliente limitada a su prefijo**.

Si se elige AWS México por residencia de datos, usar S3 con Object Lock en la misma región.

Fuentes de precios y disponibilidad (consultadas el 2026-10-18; confirmar al contratar): [Backblaze B2 pricing explained](https://upstash.com/blog/backblaze-b2-pricing-explained-2026.md), [B2 vs Wasabi](https://thewearify.com/backblaze-b2-vs-wasabi/), [Hetzner 2026 price increase](https://findstack.com/resources/hetzner-price-increase-2026), [Hetzner CPX21 US vs EU](https://sparecores.com/server/hcloud/cpx21), [AWS Mexico (Central) Region](https://aws.amazon.com/blogs/aws/now-open-aws-mexico-central-region).

## 3. Qué se probó en local

| Prueba | Resultado |
|---|---|
| Imagen del backend (sin OCR, para pruebas) | Construye (731 MB). Detectó que `numpy` y `Pillow` se importaban sin estar en `requirements.txt`; ya están |
| `GRUPO-PRUEBA-B` en contenedores (app + workers) | La app arranca con secretos de OpenBao, responde en modo seguro, alcanza la base de control y exige sesión; el worker se registra en la cola |
| Entorno del proceso de la app | No conserva la credencial de OpenBao; corre como uid 10001 |
| gocryptfs con la contraseña envuelta en OpenBao (contenedor Linux con FUSE) | Ni nombres ni contenido legibles en disco; vista vacía al desmontar; se lee al volver a montar; contraseña equivocada rechazada |
| Caddyfile y compose del plano de control | Validados con Caddy 2.11.4 y `docker compose config` |
| Cambio de política de OpenBao | Exige token de plataforma + 2 llaves (endpoint autenticado `sys/generate-root-token`) |

No se pudo probar en local: TLS real, Keycloak en modo `start` detrás del proxy, montaje de gocryptfs en el host y el destino S3 con Object Lock. Se prueban en el servidor con esta guía.

## 4. Guía de despliegue

1. **Contratar** el VPS (Ubuntu 24.04, 16 GB) y el bucket B2. Apuntar el DNS: `accesos.<dominio>` y `<cliente>.<dominio>` al VPS.
2. **Usuario de operación:** crear `facturas-op` con su llave SSH y ejecutar
   `sudo bash deploy/servidor/preparar-servidor.sh facturas-op`.
3. **Código:** copiar el repositorio a `/opt/facturas` e instalar
   `/opt/facturas/venv/bin/pip install -r requirements-operacion.txt`.
4. **Imagen:** `docker build -f deploy/app/Dockerfile -t facturas-app:produccion .` (con OCR).
5. **Configuración del plano de control:** crear `/etc/facturas/control.env` (permisos 600) con `DOMINIO`, `CORREO_TLS`, `PRIMER_CLIENTE_URL`, SMTP y contraseñas aleatorias. Colocar la raíz de atestación de las llaves en `deploy/identidad/truststores/` y fijar sus AAGUID en el realm.
6. **Levantar el plano de control** y **inicializar OpenBao sin `--desarrollo`:** anotar las 3 llaves por separado y guardar el token de plataforma fuera del servidor.
   `python -m app.plataforma.secretos inicializar`, después `secretos guardar-plataforma --desde /etc/facturas/control.env`.
7. **Primer cliente:**
   - `python -m app.plataforma.tenants alta --clave GRUPO-DEMO ...`, con `--copiar-desde` si se migra desde la máquina actual (volcado y restauración).
   - `python -m app.plataforma.archivos inicializar --clave GRUPO-DEMO`, después `archivos montar`.
   - Copiar los archivos a la vista montada y fijar `ARCHIVOS_VISIBLES=/srv/facturas/GRUPO-DEMO/archivos` y `CONTROL_RED=facturas_control` en su archivo privado.
   - `python -m app.plataforma.respaldos configurar-destino --clave GRUPO-DEMO --repositorio s3:https://<endpoint>/<bucket>/grupo-demo`.
   - `python -m app.plataforma.tenants desplegar --clave GRUPO-DEMO --imagen facturas-app:produccion`.
   - Copiar `deploy/servidor/clientes/plantilla.caddy.ejemplo` como `grupo-demo.caddy` y recargar el proxy.
   - Registrar `https://grupo-demo.<dominio>/auth/callback` como URL de regreso en Keycloak.
8. **Director:** `python -m app.seguridad.instalar director --correo <correo real> --nombre "<nombre>"` y registrar las dos llaves físicas.
9. **Temporizadores:** copiar `deploy/servidor/systemd/*` a `/etc/systemd/system/` y activar
   `facturas-respaldos@GRUPO-DEMO.timer`, `facturas-restauracion@GRUPO-DEMO.timer` y `facturas-inactividad.timer`.
10. **Verificación final:**
    - `tenants verificar`;
    - `respaldos respaldar` y `respaldos probar-restauracion`;
    - entrar con la llave física;
    - confirmar que `https://accesos.<dominio>/admin` responde 404 desde fuera.

## 5. Pendiente

- Prueba de penetración externa y revisión de amenazas con riesgo inicial ≥ 12 antes de abrir a clientes.
- Separar en la red compartida las apps de distintos clientes. Hoy se alcanzan entre sí por HTTP en `facturas_control`, aunque no a las bases de los demás. Se resuelve con una red por cliente entre el proxy y su app.
- SMTP real (proveedor transaccional) y DNS con SPF, DKIM y DMARC.
