"""Respaldos cifrados por cliente y restauración de prueba (D-025, auditoria-alertas §6).

Uso:
    python -m app.plataforma.respaldos respaldar --clave GRUPO-DEMO
    python -m app.plataforma.respaldos probar-restauracion --clave GRUPO-DEMO
    python -m app.plataforma.respaldos listar --clave GRUPO-DEMO

- Un repositorio restic por cliente, con su propio usuario en el destino. La contraseña
  del repositorio sólo existe cifrada con la clave `<cliente>-respaldos` de OpenBao.
- Diario (pérdida máxima 24 h): volcado de la base con la cuenta `tenant_respaldo` y
  carpeta de archivos del cliente.
- Destino en desarrollo: rest-server en modo sólo anexado (nadie puede borrar desde el
  cliente). En producción: bucket S3 con Object Lock; la retención (30 diarios, 12
  mensuales, 7 anuales) la aplica el ciclo de vida del bucket, no el servidor.
- La restauración de prueba usa un PostgreSQL temporal y desechable: nunca toca la base viva.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from app.plataforma import secretos, tenants

RESTIC = "restic/restic:0.19.1"
POSTGRES = "postgres:17-alpine"
TABLAS_VERIFICADAS = ("core.facturas", "core.lotes_carga", "finance.ventas", "catalog.sucursales",
                      "catalog.proveedores", "audit.correcciones")


class RespaldoError(RuntimeError):
    pass


def _red() -> str:
    return os.environ.get("RESPALDOS_RED") or f"{tenants.RAIZ.name.lower()}_control"


def _credenciales(clave: str) -> dict:
    env = tenants.leer_entorno(tenants.ruta_entorno(clave))
    if not env.get("SECRETOS_RESPALDOS_ROLE_ID"):
        raise RespaldoError(f"{clave} no tiene identidad de respaldos (ejecute tenants migrar-secretos).")
    datos = secretos.secretos_respaldos(clave, env["SECRETOS_RESPALDOS_ROLE_ID"], env["SECRETOS_RESPALDOS_SECRET_ID"])
    return {**datos, "env": env}


def _restic(cred: dict, *args: str, entrada: bytes | None = None, montajes: tuple[str, ...] = ()) -> bytes:
    """Ejecuta restic en un contenedor efímero; los secretos viajan por variables de entorno, no por argumentos."""
    comando = ["docker", "run", "--rm", "-i", "--network", _red(), "-e", "RESTIC_REPOSITORY", "-e", "RESTIC_PASSWORD"]
    # Destino S3: credenciales propias del cliente, limitadas a su prefijo del bucket.
    s3 = {k: cred[k.lower()] for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION") if cred.get(k.lower())}
    for k in s3:
        comando += ["-e", k]
    for m in montajes:
        comando += ["-v", m]
    comando += [RESTIC, *args]
    entorno = {**os.environ, **s3, "RESTIC_REPOSITORY": cred["repositorio"], "RESTIC_PASSWORD": cred["password_repositorio"]}
    r = subprocess.run(comando, input=entrada, capture_output=True, env=entorno)
    if r.returncode != 0:
        raise RespaldoError(f"restic {args[0]} falló: {r.stderr.decode(errors='replace')[-400:]}")
    return r.stdout


def _asegurar_repositorio(cred: dict) -> None:
    try:
        _restic(cred, "cat", "config")
    except RespaldoError:
        _restic(cred, "init")


def _volcado(clave: str, cred: dict) -> bytes:
    return tenants.docker_compose(
        clave, "exec", "-T", "-e", "PGPASSWORD", "db",
        "pg_dump", "-h", "127.0.0.1", "-U", cred["base_usuario"], "-d", "facturas", "-Fc", "--no-owner", "--no-privileges",
        env_extra={"PGPASSWORD": cred["base_password"]},
    )


def _registrar(tipo: str, clave: str, resultado: str = "EXITO", **detalle) -> None:
    from app.seguridad import control

    try:
        with control.conexion_control() as conn:
            tenant = control.tenant_por_clave(conn, clave)
            control.registrar_evento(conn, tipo, resultado, actor_tipo="SISTEMA", tenant_id=tenant["id"] if tenant else None,
                                     modulo="OPERACION", accion="RESPALDO", detalle=detalle)
    except Exception as exc:  # la bitácora no debe ocultar el resultado del respaldo
        print(f"Aviso: no se pudo registrar en la bitácora ({type(exc).__name__})", file=sys.stderr)


def respaldar(clave: str) -> dict:
    inicio = time.monotonic()
    cred = _credenciales(clave)
    _asegurar_repositorio(cred)
    volcado = _volcado(clave, cred)
    base = json.loads(_restic(cred, "backup", "--json", "--stdin", "--stdin-filename", "base/facturas.dump",
                              "--tag", f"tenant:{clave}", "--tag", "tipo:base", entrada=volcado).splitlines()[-1])
    carpeta = Path(cred["env"]["FACTURAS_UPLOAD_DIR"]).resolve()
    carpeta.mkdir(parents=True, exist_ok=True)
    archivos = json.loads(_restic(cred, "backup", "--json", "/datos/archivos", "--tag", f"tenant:{clave}", "--tag", "tipo:archivos",
                                  montajes=(f"{carpeta.as_posix()}:/datos/archivos:ro",)).splitlines()[-1])
    resumen = {
        "snapshot_base": base["snapshot_id"][:8], "bytes_base": len(volcado),
        "snapshot_archivos": archivos["snapshot_id"][:8], "archivos": archivos.get("total_files_processed"),
        "segundos": round(time.monotonic() - inicio, 1),
    }
    _registrar("RESPALDO", clave, **resumen)
    return resumen


def configurar_destino(clave: str, repositorio: str, *, access_key_id: str, secret_access_key: str, region: str) -> None:
    """Cambia el destino del cliente a S3 (Object Lock). La contraseña del repositorio no cambia."""
    bao = secretos.plataforma()
    actual = bao.leer(f"tenants/{clave}/respaldos")
    actual.update({
        "repositorio": repositorio, "destino": "S3 con Object Lock",
        "aws_access_key_id": access_key_id, "aws_secret_access_key": secret_access_key, "aws_default_region": region,
    })
    bao.escribir(f"tenants/{clave}/respaldos", actual)


def listar(clave: str) -> list[dict]:
    cred = _credenciales(clave)
    return [{"id": s["short_id"], "fecha": s["time"][:19], "etiquetas": s.get("tags", [])}
            for s in json.loads(_restic(cred, "snapshots", "--json"))]


def _conteos(cursor_sql) -> dict[str, int]:
    return {t: cursor_sql(f"SELECT count(*) FROM {t}") for t in TABLAS_VERIFICADAS}


def probar_restauracion(clave: str) -> dict:
    """Restaura el último respaldo en un PostgreSQL temporal y compara con la base viva."""
    inicio = time.monotonic()
    cred = _credenciales(clave)
    volcado = _restic(cred, "dump", "latest", "/base/facturas.dump", "--tag", "tipo:base")
    nombre = f"restauracion-{clave.lower()}-{int(time.time())}"
    password_temporal = secrets_token()
    subprocess.run(["docker", "run", "-d", "--rm", "--name", nombre, "-e", "POSTGRES_PASSWORD", POSTGRES],
                   check=True, capture_output=True, env={**os.environ, "POSTGRES_PASSWORD": password_temporal})
    try:
        _esperar_postgres(nombre)
        r = subprocess.run(["docker", "exec", "-i", nombre, "pg_restore", "-U", "postgres", "-d", "postgres", "--no-owner",
                            "--no-privileges", "--exit-on-error"], input=volcado, capture_output=True)
        if r.returncode != 0:
            raise RespaldoError(f"pg_restore falló: {r.stderr.decode(errors='replace')[-400:]}")

        def contar_restaurada(consulta: str) -> int:
            salida = subprocess.run(["docker", "exec", nombre, "psql", "-U", "postgres", "-At", "-c", consulta],
                                    capture_output=True, check=True)
            return int(salida.stdout.decode().strip())

        restaurada = _conteos(contar_restaurada)
    finally:
        subprocess.run(["docker", "rm", "-f", nombre], capture_output=True)

    # Base viva, contada con la misma cuenta de respaldos (ve todo, no escribe nada).
    def contar_viva(consulta: str) -> int:
        salida = tenants.docker_compose(clave, "exec", "-T", "-e", "PGPASSWORD", "db", "psql", "-h", "127.0.0.1",
                                        "-U", cred["base_usuario"], "-d", "facturas", "-At", "-c", consulta,
                                        env_extra={"PGPASSWORD": cred["base_password"]})
        return int(salida.decode().strip())

    viva = _conteos(contar_viva)
    listado = _restic(cred, "ls", "latest", "--tag", "tipo:archivos", "--json").decode().splitlines()
    en_respaldo = sum(1 for linea in listado if '"type":"file"' in linea)
    carpeta = Path(cred["env"]["FACTURAS_UPLOAD_DIR"])
    en_disco = sum(1 for f in carpeta.rglob("*") if f.is_file()) if carpeta.exists() else 0
    diferencias = {t: (viva[t], restaurada[t]) for t in TABLAS_VERIFICADAS if viva[t] != restaurada[t]}
    resultado = {
        "tablas": restaurada, "diferencias_con_la_base_viva": diferencias,
        "archivos_en_respaldo": en_respaldo, "archivos_en_disco": en_disco,
        "segundos": round(time.monotonic() - inicio, 1),
    }
    # Diferencias pequeñas son esperables si hubo actividad después del último respaldo.
    _registrar("RESTAURACION_PROBADA", clave, "EXITO", **resultado)
    return resultado


def secrets_token() -> str:
    import secrets as _s

    return _s.token_urlsafe(24)


def _esperar_postgres(nombre: str) -> None:
    for _ in range(60):
        r = subprocess.run(["docker", "exec", nombre, "pg_isready", "-U", "postgres"], capture_output=True)
        if r.returncode == 0:
            # pg_isready responde antes de terminar la inicialización: confirmar con una consulta.
            q = subprocess.run(["docker", "exec", nombre, "psql", "-U", "postgres", "-c", "SELECT 1"], capture_output=True)
            if q.returncode == 0:
                return
        time.sleep(1)
    raise RespaldoError("El PostgreSQL temporal no arrancó")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.plataforma.respaldos")
    sub = parser.add_subparsers(dest="comando", required=True)
    for nombre, ayuda in (("respaldar", "Respaldo cifrado de la base y los archivos del cliente"),
                          ("probar-restauracion", "Restaura el último respaldo en una base temporal y compara"),
                          ("listar", "Lista los respaldos del cliente")):
        sub.add_parser(nombre, help=ayuda).add_argument("--clave", required=True)
    c = sub.add_parser("configurar-destino", help="Usa un bucket S3 con Object Lock como destino del cliente")
    c.add_argument("--clave", required=True)
    c.add_argument("--repositorio", required=True, help="p. ej. s3:https://s3.us-west-004.backblazeb2.com/<bucket>/<cliente>")
    c.add_argument("--region", default="us-west-004")
    args = parser.parse_args(argv)
    clave = args.clave.upper()
    if args.comando == "configurar-destino":
        import getpass

        configurar_destino(clave, args.repositorio, access_key_id=getpass.getpass("Key ID del cliente: "),
                           secret_access_key=getpass.getpass("Application key: "), region=args.region)
        print(f"{clave}: destino de respaldos actualizado (credenciales en OpenBao)")
        return 0
    try:
        if args.comando == "respaldar":
            print(respaldar(clave))
        elif args.comando == "probar-restauracion":
            print(json.dumps(probar_restauracion(clave), indent=2, ensure_ascii=False))
        else:
            for s in listar(clave):
                print(s)
        return 0
    except (RespaldoError, secretos.SecretosError, tenants.AltaError) as error:
        _registrar("RESPALDO", clave, "ERROR", error=str(error)[:300])
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
