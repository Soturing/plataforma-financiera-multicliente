# Fase 7 (parte 1) — Secretos, claves por cliente y respaldos cifrados

Estado: implementado en local (2026-10-18). Decisión: D-025. Referencias: [arquitectura-aislamiento.md](arquitectura-aislamiento.md) §8–§10 y [auditoria-alertas.md](auditoria-alertas.md) §5–§6.

## 1. Qué hay

| Pieza | Dónde | Qué hace |
|---|---|---|
| **OpenBao 2.7.1** | servicio `secretos` (perfil `identidad`, 127.0.0.1:8200) | Secretos de la plataforma y claves por cliente, con bitácora de auditoría propia (`/openbao/logs/auditoria.log`) |
| Inicialización y apertura | `python -m app.plataforma.secretos` | 3 llaves de desbloqueo (se necesitan 2); el token raíz se revoca al terminar; el aprovisionamiento usa un token con política `plataforma` |
| Claves por cliente | Transit: `<CLIENTE>-datos`, `<CLIENTE>-respaldos` | AES-256-GCM, no exportables, sin borrado desde la plataforma; rotación con `secretos rotar` |
| Identidades por cliente | AppRole: `<CLIENTE>-app`, `<CLIENTE>-respaldos` | Cada una lee sólo sus secretos y usa sólo su clave; atadas a 127.0.0.1 y a la red interna de Docker |
| Secretos del cliente | KV: `tenants/<CLIENTE>/{base, app, respaldos}` | Las contraseñas de las bases salieron de `config/tenants/private/*.env`; ese archivo ahora sólo tiene configuración y las credenciales de arranque |
| **Respaldos** | `python -m app.plataforma.respaldos` | restic 0.19.1, un repositorio por cliente; base (con la cuenta de sólo lectura `tenant_respaldo`) y archivos |
| Destino de desarrollo | servicio `respaldos-destino` (rest-server, sólo anexado) | Nadie puede borrar respaldos con las credenciales del cliente; cada cliente sólo ve su repositorio |

### Cómo se protege cada cosa

- **La app** de un cliente obtiene su conexión a la base con **su** identidad (`servir`). No puede leer las contraseñas de administración ni nada de otro cliente.
- **La contraseña del repositorio de respaldos** sólo existe cifrada con la clave `<CLIENTE>-respaldos`. Destruir esa clave al final de la retención vuelve ilegibles todos sus respaldos (destrucción criptográfica, §10).
- **Repetir un alta** no cambia la contraseña del repositorio: los respaldos anteriores siguen siendo legibles.
- **La verificación de aislamiento** ahora también rechaza cualquier cuenta con `BYPASSRLS` que no sea `tenant_respaldo`.

## 2. Operación

```powershell
# Una sola vez (en local guarda llaves y token en config/secretos/private, ignorado por git)
.\.venv\Scripts\python.exe -m app.plataforma.secretos inicializar --desarrollo

# Tras CADA reinicio de OpenBao (reinicio del equipo o del contenedor): sin esto la app no arranca
.\.venv\Scripts\python.exe -m app.plataforma.secretos abrir --desde-archivo   # local
.\.venv\Scripts\python.exe -m app.plataforma.secretos abrir                   # producción: pide 2 llaves

# Respaldo diario y prueba de restauración (trimestral como mínimo)
.\.venv\Scripts\python.exe -m app.plataforma.respaldos respaldar --clave GRUPO-DEMO
.\.venv\Scripts\python.exe -m app.plataforma.respaldos probar-restauracion --clave GRUPO-DEMO
.\.venv\Scripts\python.exe -m app.plataforma.respaldos listar --clave GRUPO-DEMO

# Rotar una clave (lo ya cifrado sigue descifrándose con la versión anterior)
.\.venv\Scripts\python.exe -m app.plataforma.secretos rotar --clave GRUPO-DEMO --uso datos
```

Respaldos y restauraciones quedan en la bitácora del plano de control (`RESPALDO`, `RESTAURACION_PROBADA`).

### Resultado en local

- Respaldo de `GRUPO-DEMO`: base de 980 KB (formato comprimido) y 426 archivos en 18 s.
- Restauración de prueba en un PostgreSQL desechable: mismos conteos en las 6 tablas verificadas y los mismos 426 archivos; sin diferencias con la base viva.

## 3. Para producción

1. **Llaves de desbloqueo:** `secretos inicializar` **sin** `--desarrollo` las muestra una sola vez. Repártelas para que nadie tenga 2 en el mismo lugar: por ejemplo, una impresa en caja fuerte, otra en un gestor de contraseñas personal y otra en un sobre con un tercero de confianza. Con la excepción D-020 (una sola persona) conviene que al menos una llave esté fuera de la oficina.
2. **Token de plataforma:** no se guarda en el servidor; se usa sólo para dar de alta o rotar, y se renueva antes de 30 días.
3. **TLS** en OpenBao, por certificado propio o detrás del proxy con TLS hasta el contenedor.
4. **Destino S3 con Object Lock** (modo *compliance*), un prefijo y una credencial por cliente. La retención (30 diarios, 12 mensuales, 7 anuales) la aplica la regla de ciclo de vida del bucket, nunca el servidor. Esa retención debe validarse legalmente (auditoria-alertas §5).
5. **Programar** `respaldar` a diario y `probar-restauracion` cada trimestre, con alerta si fallan.
6. **Disco cifrado (LUKS)** en el VPS, si el proveedor lo permite.

## 4. Cambio respecto a la propuesta: cifrado de archivos

Se propuso cifrar cada archivo dentro de la app (envelope). Al revisar el código hay unos 80 puntos que abren archivos por ruta, incluidos PaddleOCR y PyMuPDF. Cifrar en la app obligaría a dejar copias descifradas temporales en disco, justo lo que se quiere evitar.

**Decisión (D-025):** los archivos se cifran **por cliente a nivel de sistema de archivos** (gocryptfs) en el servidor Linux, con la clave envuelta por `<CLIENTE>-datos` en OpenBao. Implementado y probado en la parte 2: ver [despliegue-servidor.md](despliegue-servidor.md).

## 5. Pendiente de la fase 7

- Elegir VPS y bucket S3 y ejecutar [despliegue-servidor.md](despliegue-servidor.md).
- SMTP real para los avisos.
- Prueba de penetración externa y revisión de las amenazas con riesgo inicial ≥ 12.
