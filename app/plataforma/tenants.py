"""Alta y operación del data plane de cada cliente (fase 5, D-016, D-024).

Uso:
    python -m app.plataforma.tenants alta --clave GRUPO-B --nombre "Grupo B" --puerto-db 5441 --puerto-app 8012 \\
        --restaurante REST-UNO:"Restaurante Uno" --sucursal CENTRO:"Centro":REST-UNO
    python -m app.plataforma.tenants alta --clave GRUPO-DEMO ... --copiar-desde ../otra/.env --migraciones-hasta 031 \\
        --archivos-desde ../otra/data/uploads
    python -m app.plataforma.tenants servir --clave GRUPO-DEMO
    python -m app.plataforma.tenants verificar --clave GRUPO-DEMO
    python -m app.plataforma.tenants pruebas --clave GRUPO-DEMO -q --basetemp "%TEMP%/pt-fa"

Cada cliente tiene su archivo privado `config/tenants/private/<CLAVE>.env` (ignorado
por git) con sus credenciales, y su proyecto Docker `fa-<clave>` con base, volumen y
red propios. El alta sólo deja activo al cliente si la verificación de aislamiento pasa
(arquitectura-aislamiento §13).
"""
from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlparse

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

RAIZ = Path(__file__).resolve().parents[2]
PRIVADO = RAIZ / "config" / "tenants" / "private"
PLANTILLA = RAIZ / "deploy" / "tenant" / "compose.yaml"
MIGRACIONES = RAIZ / "db" / "migrations"
CLAVE_VALIDA = re.compile(r"^[A-Z0-9-]{2,40}$")


class AltaError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Entorno privado del cliente


def ruta_entorno(clave: str) -> Path:
    return PRIVADO / f"{clave}.env"


def leer_entorno(ruta: Path) -> dict[str, str]:
    valores: dict[str, str] = {}
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.lstrip().startswith("#"):
                k, v = linea.split("=", 1)
                valores[k.strip()] = v.strip()
    return valores


def preparar_entorno(clave: str, nombre: str, puerto_db: int, puerto_app: int) -> dict[str, str]:
    """Crea o completa el archivo privado del cliente; nunca rota secretos existentes."""
    ruta = ruta_entorno(clave)
    env = leer_entorno(ruta)
    for k in ("DP_ADMIN_PASSWORD", "TENANT_OWNER_PASSWORD", "TENANT_RUNTIME_PASSWORD"):
        env.setdefault(k, secrets.token_urlsafe(32))
    env.update({
        "DP_DB_PORT": str(puerto_db),
        "FACTURAS_TENANT_CLAVE": clave,
        "FACTURAS_TENANT_NOMBRE": nombre,
        "FACTURAS_APP_URL": f"http://127.0.0.1:{puerto_app}",
        "FACTURAS_APP_PORT": str(puerto_app),
        "FACTURAS_UPLOAD_DIR": (RAIZ / "data" / "tenants" / clave / "uploads").as_posix(),
        "FACTURAS_DATABASE_URL": url_base(env, "tenant_runtime", "TENANT_RUNTIME_PASSWORD", puerto_db),
    })
    PRIVADO.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        "# Data plane del cliente. Privado: nunca versionar (politica-repositorio.md).\n"
        + "".join(f"{k}={v}\n" for k, v in sorted(env.items())),
        encoding="utf-8",
    )
    return env


def url_base(env: dict[str, str], usuario: str, clave_password: str, puerto: int | str | None = None) -> str:
    puerto = puerto or env["DP_DB_PORT"]
    return f"postgresql://{usuario}:{quote(env[clave_password], safe='')}@127.0.0.1:{puerto}/facturas"


def conectar(url: str, tenant: str | None = None, sucursales: str = "*", **kw) -> psycopg.Connection:
    opciones = f"-c app.tenant={tenant} -c app.sucursales={sucursales}" if tenant else None
    return psycopg.connect(url, options=opciones, row_factory=dict_row, connect_timeout=10, **kw)


# --------------------------------------------------------------------------- #
# Contenedor


def docker_compose(clave: str, *args: str, entrada: bytes | None = None, env_extra: dict | None = None) -> bytes:
    comando = [
        "docker", "compose", "-p", f"fa-{clave.lower()}", "-f", str(PLANTILLA),
        "--env-file", str(ruta_entorno(clave)), *args,
    ]
    resultado = subprocess.run(comando, input=entrada, capture_output=True, env={**os.environ, **(env_extra or {})})
    if resultado.returncode != 0:
        raise AltaError(f"docker compose {' '.join(args[:2])} falló: {resultado.stderr.decode(errors='replace')[-500:]}")
    return resultado.stdout


def levantar_base(clave: str, env: dict[str, str]) -> None:
    docker_compose(clave, "up", "-d", "db")
    admin = url_base(env, "dp_admin", "DP_ADMIN_PASSWORD")
    for _ in range(60):
        try:
            with conectar(admin) as c:
                c.execute("SELECT 1")
                return
        except psycopg.OperationalError:
            time.sleep(2)
    raise AltaError("La base del cliente no respondió a tiempo")


def crear_roles(env: dict[str, str]) -> None:
    """Propietaria para migraciones y cuenta de la app sin privilegios (arquitectura-aislamiento §8)."""
    with conectar(url_base(env, "dp_admin", "DP_ADMIN_PASSWORD"), autocommit=True) as c:
        for rol, clave_pw, extra in (
            ("tenant_owner", "TENANT_OWNER_PASSWORD", "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"),
            ("tenant_runtime", "TENANT_RUNTIME_PASSWORD", "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"),
        ):
            existe = c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (rol,)).fetchone()
            c.execute(sql.SQL("{} ROLE {} LOGIN " + extra + " PASSWORD {}").format(
                sql.SQL("ALTER" if existe else "CREATE"), sql.Identifier(rol), sql.Literal(env[clave_pw])
            ))
        c.execute("ALTER DATABASE facturas OWNER TO tenant_owner")
        c.execute("ALTER SCHEMA public OWNER TO tenant_owner")
        c.execute("REVOKE ALL ON DATABASE facturas FROM PUBLIC")
        c.execute("GRANT CONNECT ON DATABASE facturas TO tenant_owner, tenant_runtime")
        c.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")


# --------------------------------------------------------------------------- #
# Datos y migraciones


def copiar_base(clave: str, env: dict[str, str], origen_envfile: Path) -> None:
    """Copia la base de origen como tenant_owner (todo queda de su propiedad)."""
    origen = leer_entorno(origen_envfile)
    url = urlparse(origen["FACTURAS_DATABASE_URL"])
    host = "host.docker.internal" if url.hostname in ("localhost", "127.0.0.1") else url.hostname
    volcado = docker_compose(
        clave, "exec", "-T", "-e", "PGPASSWORD", "db",
        "pg_dump", "-h", host, "-p", str(url.port or 5432), "-U", url.username, "-d", url.path.lstrip("/"),
        "--no-owner", "--no-privileges",
        env_extra={"PGPASSWORD": origen.get("POSTGRES_PASSWORD") or (url.password or "")},
    )
    docker_compose(
        clave, "exec", "-T", "-e", "PGPASSWORD", "db",
        "psql", "-v", "ON_ERROR_STOP=1", "-q", "-h", "127.0.0.1", "-U", "tenant_owner", "-d", "facturas",
        entrada=volcado, env_extra={"PGPASSWORD": env["TENANT_OWNER_PASSWORD"]},
    )


def base_inicializada(env: dict[str, str]) -> bool:
    with conectar(url_base(env, "tenant_owner", "TENANT_OWNER_PASSWORD")) as c:
        return c.execute("SELECT to_regclass('core.facturas') IS NOT NULL AS hay").fetchone()["hay"]


def aplicar_migraciones(env: dict[str, str], *, hasta_previas: str | None = None) -> list[str]:
    """Aplica en orden las migraciones pendientes como propietaria y las registra."""
    archivos = sorted(MIGRACIONES.glob("*.sql"))
    aplicadas: list[str] = []
    with conectar(url_base(env, "tenant_owner", "TENANT_OWNER_PASSWORD"), autocommit=True) as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS public.migraciones_aplicadas (nombre text PRIMARY KEY, aplicada_en timestamptz NOT NULL DEFAULT now())"
        )
        if hasta_previas:
            for a in archivos:
                if a.name[:3] <= hasta_previas:
                    c.execute("INSERT INTO public.migraciones_aplicadas (nombre) VALUES (%s) ON CONFLICT DO NOTHING", (a.name,))
        hechas = {f["nombre"] for f in c.execute("SELECT nombre FROM public.migraciones_aplicadas").fetchall()}
        for a in archivos:
            if a.name in hechas:
                continue
            with c.transaction():
                c.execute(a.read_text(encoding="utf-8"))
                c.execute("INSERT INTO public.migraciones_aplicadas (nombre) VALUES (%s)", (a.name,))
            aplicadas.append(a.name)
    return aplicadas


def fijar_identidad(env: dict[str, str], clave: str) -> None:
    with conectar(url_base(env, "tenant_owner", "TENANT_OWNER_PASSWORD")) as c:
        actual = c.execute("SELECT tenant_clave FROM seguridad.identidad_tenant").fetchone()
        if actual and actual["tenant_clave"] != clave:
            raise AltaError(f"Esta base ya pertenece a {actual['tenant_clave']}")
        c.execute("INSERT INTO seguridad.identidad_tenant (tenant_clave) VALUES (%s) ON CONFLICT DO NOTHING", (clave,))


def cargar_estructura(env: dict[str, str], clave: str, restaurantes: list[str], sucursales: list[str]) -> None:
    """Restaurantes ('CLAVE:Nombre') y sucursales ('CLAVE:Nombre:RESTAURANTE') del cliente nuevo."""
    if not restaurantes and not sucursales:
        return
    with conectar(url_base(env, "tenant_owner", "TENANT_OWNER_PASSWORD"), tenant=clave) as c:
        # Las migraciones 007/009/012 siembran sucursales de demo: en un cliente nuevo
        # quedan inactivas (pendiente: separar esquema y semillas).
        c.execute("UPDATE catalog.sucursales SET activa = false WHERE clave LIKE 'DEMO-%'")
        c.execute("UPDATE catalog.restaurantes SET activo = false WHERE clave LIKE 'RESTAURANTE-DEMO%'")
        for r in restaurantes:
            rc, rn = r.split(":", 1)
            c.execute("INSERT INTO catalog.restaurantes (clave, nombre) VALUES (%s, %s) ON CONFLICT (clave) DO NOTHING", (rc, rn))
        for s in sucursales:
            sc, sn, rc = s.split(":", 2)
            c.execute(
                """INSERT INTO catalog.sucursales (clave, nombre, restaurante, restaurante_id)
                   SELECT %s, %s, r.nombre, r.id FROM catalog.restaurantes r WHERE r.clave = %s
                   ON CONFLICT (clave) DO NOTHING""",
                (sc, sn, rc),
            )


def copiar_archivos(env: dict[str, str], clave: str, origen: Path) -> int:
    """Copia los archivos al almacenamiento del cliente y reescribe sus rutas en la base."""
    destino = Path(env["FACTURAS_UPLOAD_DIR"])
    destino.mkdir(parents=True, exist_ok=True)
    shutil.copytree(origen, destino, dirs_exist_ok=True)
    viejo, nuevo = str(origen.resolve()), str(destino.resolve())
    total = 0
    with conectar(url_base(env, "tenant_owner", "TENANT_OWNER_PASSWORD"), tenant=clave) as c:
        # audit.documentos_eliminados es de sólo anexado: conserva la ruta original como evidencia.
        for tabla, columna in (("core.facturas", "archivo_url"), ("core.lotes_carga", "archivo_original_url"),
                               ("core.documentos_duplicados", "archivo_url")):
            total += c.execute(
                # starts_with y no LIKE: las rutas de Windows llevan "\\", que LIKE trata como escape.
                f"UPDATE {tabla} SET {columna} = %s || substr({columna}, length(%s) + 1) WHERE starts_with({columna}, %s)",
                (nuevo, viejo, viejo),
            ).rowcount
    return total


# --------------------------------------------------------------------------- #
# Plano de control y verificación


def registrar_en_control(env: dict[str, str], clave: str, nombre: str) -> dict:
    from app.seguridad import control

    with conectar(env["FACTURAS_DATABASE_URL"], tenant=clave) as datos:
        restaurantes = datos.execute("SELECT id, clave, nombre, activo FROM catalog.restaurantes ORDER BY clave").fetchall()
        sucursales = datos.execute(
            """SELECT s.id, s.clave, s.nombre, s.activa, r.clave AS restaurante
               FROM catalog.sucursales s LEFT JOIN catalog.restaurantes r ON r.id = s.restaurante_id ORDER BY s.clave"""
        ).fetchall()
    with control.conexion_control() as conn:
        tenant = conn.execute(
            """INSERT INTO control.tenants (clave, nombre, data_plane_url) VALUES (%s, %s, %s)
               ON CONFLICT (clave) DO UPDATE SET nombre = EXCLUDED.nombre, data_plane_url = EXCLUDED.data_plane_url
               RETURNING *""",
            (clave, nombre, env["FACTURAS_APP_URL"]),
        ).fetchone()
        for r in restaurantes:
            conn.execute(
                """INSERT INTO control.restaurantes (tenant_id, clave, nombre, data_plane_id, activo) VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (tenant_id, clave) DO UPDATE SET nombre = EXCLUDED.nombre, data_plane_id = EXCLUDED.data_plane_id,
                   activo = EXCLUDED.activo""",
                (tenant["id"], r["clave"], r["nombre"], r["id"], r["activo"]),
            )
        for s in sucursales:
            conn.execute(
                """INSERT INTO control.sucursales (tenant_id, clave, nombre, data_plane_id, activa, restaurante_clave)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (tenant_id, clave) DO UPDATE SET nombre = EXCLUDED.nombre, data_plane_id = EXCLUDED.data_plane_id,
                   activa = EXCLUDED.activa, restaurante_clave = EXCLUDED.restaurante_clave""",
                (tenant["id"], s["clave"], s["nombre"], s["id"], s["activa"], s["restaurante"]),
            )
        control.registrar_evento(
            conn, "ALTA_CLIENTE", actor_tipo="SISTEMA", tenant_id=tenant["id"], modulo="CLIENTES", accion="ADMINISTRAR",
            detalle={"restaurantes": [r["clave"] for r in restaurantes], "sucursales": [s["clave"] for s in sucursales],
                     "data_plane": env["FACTURAS_APP_URL"]},
        )
    return {"restaurantes": [r["clave"] for r in restaurantes], "sucursales": [s["clave"] for s in sucursales]}


def verificar(clave: str, env: dict[str, str] | None = None) -> list[str]:
    """Pruebas de aislamiento de la base del cliente. Devuelve los problemas (vacío = aprobado)."""
    env = env or leer_entorno(ruta_entorno(clave))
    problemas: list[str] = []
    runtime = env["FACTURAS_DATABASE_URL"]
    with conectar(runtime) as c:
        rol = c.execute(
            "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        if any(rol.values()):
            problemas.append(f"La cuenta de la app tiene privilegios: {rol}")
        propias = c.execute("SELECT count(*) AS n FROM pg_tables WHERE tableowner = current_user").fetchone()["n"]
        if propias:
            problemas.append(f"La cuenta de la app es propietaria de {propias} tablas")
        sin_rls = c.execute(
            """SELECT n.nspname || '.' || c.relname AS tabla FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE c.relkind IN ('r', 'p') AND n.nspname IN ('ai','audit','catalog','core','finance','ocr','analytics')
                 AND NOT (c.relrowsecurity AND c.relforcerowsecurity)"""
        ).fetchall()
        if sin_rls:
            problemas.append(f"Tablas sin RLS forzado: {[t['tabla'] for t in sin_rls]}")
        if c.execute("SELECT count(*) AS n FROM catalog.sucursales").fetchone()["n"]:
            problemas.append("Sin declarar tenant, la app ve filas")
    with conectar(runtime, tenant="OTRO-CLIENTE") as c:
        if c.execute("SELECT count(*) AS n FROM catalog.sucursales").fetchone()["n"]:
            problemas.append("Con otro tenant declarado, la app ve filas")
        try:
            c.execute("INSERT INTO catalog.restaurantes (clave, nombre) VALUES ('INTRUSO', 'x')")
            problemas.append("Con otro tenant declarado, la app puede escribir")
        except psycopg.Error:
            pass
    with conectar(runtime, tenant=clave) as c:
        if not c.execute("SELECT count(*) AS n FROM seguridad.identidad_tenant").fetchone()["n"]:
            problemas.append("La base no tiene identidad de tenant")
        try:
            c.execute("UPDATE seguridad.identidad_tenant SET tenant_clave = 'OTRO'")
            problemas.append("La app puede cambiar la identidad de la base")
        except psycopg.Error:
            pass
    return problemas


# --------------------------------------------------------------------------- #
# Comandos


def alta(args: argparse.Namespace) -> int:
    clave = args.clave.upper()
    if not CLAVE_VALIDA.match(clave):
        raise AltaError("La clave debe tener 2–40 letras mayúsculas, números o guiones")
    env = preparar_entorno(clave, args.nombre, args.puerto_db, args.puerto_app)
    print(f"1/7 Base propia del cliente (proyecto fa-{clave.lower()}, puerto {args.puerto_db})")
    levantar_base(clave, env)
    print("2/7 Roles tenant_owner y tenant_runtime")
    crear_roles(env)
    if base_inicializada(env):
        print("3/7 La base del cliente ya tiene datos: no se copia de nuevo")
    elif args.copiar_desde:
        print(f"3/7 Copia de datos desde {args.copiar_desde}")
        copiar_base(clave, env, Path(args.copiar_desde))
    else:
        print("3/7 Base nueva")
    aplicadas = aplicar_migraciones(env, hasta_previas=args.migraciones_hasta if args.copiar_desde else None)
    print(f"4/7 Migraciones aplicadas: {', '.join(aplicadas) or 'ninguna pendiente'}")
    fijar_identidad(env, clave)
    cargar_estructura(env, clave, args.restaurante or [], args.sucursal or [])
    if args.archivos_desde:
        print(f"5/7 Archivos: {copiar_archivos(env, clave, Path(args.archivos_desde))} rutas actualizadas")
    else:
        Path(env["FACTURAS_UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)
        print("5/7 Almacenamiento propio vacío")
    print("6/7 Verificación de aislamiento")
    problemas = verificar(clave, env)
    if problemas:
        for p in problemas:
            print(f"   ✗ {p}")
        print("El cliente NO se registra hasta corregir los problemas.")
        return 1
    print(f"7/7 Registro en el plano de control: {registrar_en_control(env, clave, args.nombre)}")
    print(f"Listo. Arranque: python -m app.plataforma.tenants servir --clave {clave}")
    return 0


def servir(args: argparse.Namespace) -> int:
    clave = args.clave.upper()
    env = leer_entorno(ruta_entorno(clave))
    if not env:
        raise AltaError(f"No existe el cliente {clave}")
    entorno = {**os.environ, **{k: v for k, v in env.items() if k.startswith("FACTURAS_")}}
    puerto = str(args.puerto or env["FACTURAS_APP_PORT"])
    comando = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", puerto]
    print(f"Sirviendo {clave} en http://127.0.0.1:{puerto} (base 127.0.0.1:{env['DP_DB_PORT']})", flush=True)
    try:
        return subprocess.call(comando, env=entorno, cwd=RAIZ)
    except KeyboardInterrupt:  # Ctrl-C detiene uvicorn; no es un error
        return 0


def pruebas(args: argparse.Namespace, extra: list[str]) -> int:
    """Corre pytest contra el data plane del cliente: la app con tenant_runtime (RLS) y la
    preparación/limpieza de datos de prueba como propietaria (tests/apoyo_db.py)."""
    clave = args.clave.upper()
    env = leer_entorno(ruta_entorno(clave))
    if not env:
        raise AltaError(f"No existe el cliente {clave}")
    entorno = {**os.environ, **{k: v for k, v in env.items() if k.startswith("FACTURAS_")},
               "TENANT_OWNER_URL": url_base(env, "tenant_owner", "TENANT_OWNER_PASSWORD"),
               "FACTURAS_OCR_AUTOSTART_WORKERS": "false"}
    return subprocess.call([sys.executable, "-m", "pytest", *(extra or ["-q"])], env=entorno, cwd=RAIZ)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.plataforma.tenants")
    sub = parser.add_subparsers(dest="comando", required=True)
    a = sub.add_parser("alta", help="Crea el data plane de un cliente y lo registra si pasa la verificación")
    a.add_argument("--clave", required=True)
    a.add_argument("--nombre", required=True)
    a.add_argument("--puerto-db", type=int, required=True)
    a.add_argument("--puerto-app", type=int, required=True)
    a.add_argument("--copiar-desde", help="Archivo .env de la base de origen (sólo para migrar un cliente existente)")
    a.add_argument("--migraciones-hasta", default="031", help="Última migración que ya tiene la base copiada")
    a.add_argument("--archivos-desde", help="Carpeta de archivos de origen")
    a.add_argument("--restaurante", action="append", help="CLAVE:Nombre (cliente nuevo)")
    a.add_argument("--sucursal", action="append", help="CLAVE:Nombre:RESTAURANTE (cliente nuevo)")
    s = sub.add_parser("servir", help="Arranca el backend del cliente con su entorno privado")
    s.add_argument("--clave", required=True)
    s.add_argument("--puerto", type=int)
    v = sub.add_parser("verificar", help="Ejecuta las pruebas de aislamiento de la base del cliente")
    v.add_argument("--clave", required=True)
    p = sub.add_parser("pruebas", help="Corre pytest contra el data plane del cliente (argumentos extra van a pytest)")
    p.add_argument("--clave", required=True)
    args, extra = parser.parse_known_args(argv)
    if extra and args.comando != "pruebas":
        parser.error(f"Argumentos no reconocidos: {extra}")
    try:
        if args.comando == "alta":
            return alta(args)
        if args.comando == "servir":
            return servir(args)
        if args.comando == "pruebas":
            return pruebas(args, extra)
        problemas = verificar(args.clave.upper())
        print("Aislamiento verificado" if not problemas else "\n".join(f"✗ {p}" for p in problemas))
        return 1 if problemas else 0
    except AltaError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
