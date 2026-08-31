# Política de repositorio y control de versiones

## Objetivo

El repositorio representa el producto reutilizable, no los datos de una consultoría ni la configuración privada de un cliente. Todo contenido versionado debe poder compartirse entre entornos sin revelar información de ningún grupo restaurantero.

## Contenido permitido

- código fuente y migraciones de esquema;
- documentación de arquitectura, amenazas, roles y operación;
- fixtures inequívocamente sintéticos con organizaciones, RFC, personas e importes ficticios;
- pruebas automatizadas y recursos visuales genéricos;
- ejemplos de configuración sin secretos.

## Contenido prohibido

- nómina, recetas, inventarios, deuda, ventas, ganancias o costos reales;
- facturas, XML fiscales, reportes, exportaciones o respaldos de clientes;
- nombres, RFC, logotipos, contactos o alias que identifiquen a un cliente o proveedor real;
- credenciales, tokens, llaves privadas, certificados con clave o archivos `.env`;
- capturas de pantalla, logs o errores que contengan información financiera o identificadores personales;
- datos de cliente en commits, ramas, etiquetas, issues, pull requests o logs de CI.

## Separación obligatoria

| Tipo de información | Ubicación permitida |
|---|---|
| Producto genérico | Repositorio privado del producto |
| Configuración por cliente | Almacén de configuración privado por entorno |
| Secretos | Gestor de secretos; nunca Git |
| Datos financieros y documentos | Base de datos y almacenamiento de objetos aislados por organización |
| Entregables y exportaciones | Almacenamiento documental autorizado; nunca el repositorio |

Los directorios `deliverables/`, `entregables/`, `output/`, `data/`, `reports/`, `exports/`, `app/static/brands/` y `config/tenants/private/` permanecen ignorados. Ignorar un archivo nuevo no elimina una versión antigua: si un dato sensible llega a un commit, se debe tratar como incidente y sanear el historial antes de publicar.

## Controles de acceso al repositorio

- repositorio privado;
- acceso sólo para integrantes asignados al producto;
- autenticación de GitHub con passkey o llave física y segundo factor de respaldo;
- rama principal protegida, cambios mediante pull request y al menos una revisión independiente;
- permisos mínimos; administración reservada al responsable de la consultora;
- salida de una persona: revocación inmediata de GitHub, CI, nube, secretos y equipos administrados;
- commits con correo `noreply` y, cuando esté disponible, firma verificable.

La consultora puede administrar todos los clientes en la aplicación, pero ese alcance operativo no autoriza copiar datos de clientes al repositorio.

## Puerta local antes de cada commit

El repositorio incluye un hook versionado que ejecuta `scripts/check_repo_safety.ps1`. Bloquea rutas confidenciales, binarios ofimáticos y patrones comunes de llaves o tokens. Se habilita una vez por clon con:

```powershell
git config core.hooksPath .githooks
```

El hook es una defensa adicional; no sustituye la revisión humana ni el escaneo de secretos del servidor.

## Respuesta si un dato sensible entra a Git

1. detener el push y cualquier despliegue relacionado;
2. revocar o rotar inmediatamente toda credencial expuesta;
3. identificar commits, ramas, etiquetas, forks, artefactos de CI y clones afectados;
4. reescribir el historial antes de publicar y verificar que el objeto ya no sea alcanzable;
5. notificar al responsable de seguridad y conservar evidencia del incidente fuera del repositorio;
6. documentar la causa y agregar un control preventivo verificable.
