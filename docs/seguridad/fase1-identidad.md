# Fase 1 — Proveedor de identidad (Keycloak)

Estado: prueba técnica completada en el entorno local (2026-10-18). Falta la verificación manual con una llave física real (§5) y los bloqueos de producción (§4).

Decisión: D-021. Plan: [plan-implementacion.md](plan-implementacion.md).

## 1. Qué se construyó

| Pieza | Ubicación |
|---|---|
| Keycloak 26.7.5 + PostgreSQL propio + Mailpit (sólo desarrollo), red `control` | `compose.yaml`, perfil `identidad` |
| Realm `facturas` versionado, sin secretos (placeholders `${...}`) | `deploy/identidad/realm-facturas.json` |
| Autenticador WebAuthn de software y cliente de pruebas | `tests/identidad/` |
| Prueba técnica automatizada | `tests/identidad/test_keycloak_fase1.py` |

### Flujo de acceso `navegador-sin-contrasena`

```text
Cookie de Keycloak ─── o ─── Formularios
                              ├── Correo (identificador primero)
                              ├── [rol requiere-llave-fisica]  → llave FIDO2 (política WebAuthn)
                              ├── [cualquier otro rol]         → passkey  o  código de recuperación
                              └── [no se usó ninguna credencial fuerte] → Deny access
```

- No existe contraseña en ningún flujo; la concesión directa y el restablecimiento por correo apuntan a un flujo que siempre deniega.
- El rol `requiere-llave-fisica` lo asignará el plano de control (fase 2) a quien tenga un rol global. Sale en el `access_token` del cliente `facturas-app` para que la aplicación lo verifique.
- El alta de autenticadores sólo ocurre por un enlace de invitación de un solo uso (24 h), nunca desde la pantalla de acceso.
- Política de llave física: atestación `direct`, autenticador externo, verificación de usuario (PIN) obligatoria, sin repetir la misma llave.
- Política de passkey: clave residente y verificación de usuario obligatorias.
- Sesión de Keycloak corta (5 min de inactividad, 8 h máximo): las sesiones largas y por rol las lleva la aplicación (fase 3).
- Bloqueo temporal tras 5 fallos en 10 minutos; eventos de acceso y de administración activados.

## 2. Cómo levantarlo y probarlo

```powershell
Copy-Item .env.example .env   # y sustituir cada CAMBIAR_*
docker compose --profile identidad up -d identidad correo-pruebas
.\.venv\Scripts\python.exe -m pytest tests/identidad -q --basetemp "$env:TEMP\pt-fa"
```

- Keycloak: `http://localhost:8180` (sólo escucha en 127.0.0.1). La primera vez tarda varios minutos.
- Correos de invitación: `http://localhost:8025`.
- Sin Keycloak en marcha, las pruebas de `tests/identidad` se omiten.
- El realm se importa sólo cuando no existe. Para aplicar cambios del JSON: `docker compose --profile identidad down -v` y volver a levantar.

## 3. Resultados de la prueba técnica

| # | Punto | Resultado | Prueba |
|---|---|---|---|
| 1 | Registro con passkey por invitación y acceso sin contraseña | Cumple | `test_invitacion_registra_passkey_y_codigos`, `test_acceso_con_passkey_entrega_identidad_verificable` |
| 2 | Llave física exigida por rol | Cumple con condiciones (§4) | `test_rol_global_rechaza_lo_que_no_es_llave_fisica_confiable` (4 casos), `test_rol_global_no_entra_con_passkey`, `test_flujo_rol_global_con_llave`, `test_rol_operativo_no_lleva_rol_global_en_el_token` |
| 3 | Reautenticación forzada (`prompt=login`, `max_age=0`) con `auth_time` verificable | Cumple | `test_reautenticacion_forzada_exige_nueva_ceremonia` |
| 4 | Códigos de recuperación en cuentas sin contraseña | Cumple; uso de un solo código, una vez | `test_codigo_de_recuperacion_sustituye_a_la_passkey_una_sola_vez` |
| 5 | Sin contraseña de respaldo silenciosa | Cumple | `test_no_existe_acceso_con_contrasena` |
| — | Conocer el correo no permite entrar ni enrolar un autenticador | Cumple | `test_usuario_sin_credencial_no_entra_ni_se_enrola` |
| — | Bloqueo temporal tras 5 fallos (4 no bloquean) | Cumple | `test_bloqueo_temporal_tras_cinco_fallos` |

Resultado: 14 pruebas, todas en verde contra Keycloak 26.7.5 local.

### Hallazgos

1. **La lista de AAGUID vacía desactiva la exigencia de llave física.** Con la lista vacía (como está hoy el realm versionado), Keycloak acepta cualquier autenticador externo, incluso uno de software con autoatestación. Con la lista configurada, rechaza la autoatestación, la atestación `none` y las cadenas emitidas por una CA que no está en su truststore ("invalid cert path").
2. **Por lo mismo, una llave real también se rechaza si la raíz de su fabricante no está en el truststore de Keycloak.** La lista de AAGUID y las raíces del fabricante van juntas.
3. **Un código de recuperación da acceso completo** sin obligar a registrar una nueva passkey ni avisar a la aplicación. `ciclo-vida-usuarios.md` §10 lo trata como recuperación: la fase 6 debe detectar ese evento, forzar el registro de un autenticador nuevo y notificar.
4. **Keycloak ignora un cambio parcial de la política WebAuthn** por API: hay que enviar la política completa. Relevante para el aprovisionamiento automático.
5. Las pruebas de rol global en desarrollo usan la lista vacía; el rechazo con lista configurada sí está probado.
6. **Además del umbral de 5 fallos, Keycloak bloquea 60 s si dos fallos llegan con menos de 1 s de diferencia** (detección de intentos rápidos). Es más estricto que `auditoria-alertas.md` §8 y se conserva; la fase 3 debe reflejar ambos bloqueos en la bitácora y en las alertas.

## 4. Bloqueos antes de producción

- Elegir el modelo de llave física (p. ej., YubiKey 5) y fijar sus AAGUID en `webAuthnPolicyAcceptableAaguids`.
- Instalar las raíces de atestación del fabricante en el truststore de Keycloak (`conf/truststores`).
- Arrancar con `start` (no `start-dev`), TLS detrás del proxy inverso, `KC_HOSTNAME` del dominio real y RP ID igual al dominio.
- Sustituir Mailpit por el servicio de correo real y eliminar la cuenta de instalación (`IDENTIDAD_ADMIN_*`) tras crear al primer director.
- Reenviar los eventos de Keycloak a la bitácora inmutable del plano de control (fase 2).

## 5. Verificación manual pendiente con llave física real

Con una llave FIDO2 real y su AAGUID y raíz configurados:

1. invitar a un usuario de prueba con rol `requiere-llave-fisica` y la acción "Registrar llave física";
2. registrar la llave desde el enlace del correo en un navegador real;
3. iniciar sesión con la llave y su PIN;
4. comprobar que una passkey del teléfono o de Windows Hello no se acepta para ese usuario; y
5. registrar la segunda llave de respaldo y comprobar que no se acepta la misma llave dos veces.

## 6. Entorno local

Durante la prueba, el equipo tenía unos 200 MB de RAM libres de 16 GB; Keycloak tardó ~4 minutos en arrancar y la batería completa entre 7 y 15 minutos. Con más memoria libre ambos tiempos bajan mucho.
