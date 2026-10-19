"""Cifrado en reposo de los archivos de cada cliente con gocryptfs (D-025).

Corre en el servidor Linux (no dentro del contenedor de la app):
    python -m app.plataforma.archivos inicializar --clave GRUPO-DEMO [--base /srv/facturas]
    python -m app.plataforma.archivos montar --clave GRUPO-DEMO
    python -m app.plataforma.archivos desmontar --clave GRUPO-DEMO
    python -m app.plataforma.archivos probar --clave GRUPO-PRUEBA-B --base /tmp/prueba   # prueba de extremo a extremo

- Cada cliente tiene `<base>/<CLAVE>/archivos.cifrados` (lo único que toca el disco y los
  respaldos de la máquina) y `<base>/<CLAVE>/archivos` (vista descifrada que gocryptfs
  monta y que el contenedor de la app recibe como /datos/uploads).
- La contraseña de gocryptfs es aleatoria y sólo se guarda cifrada con la clave
  `<CLAVE>-datos` de OpenBao (`tenants/<CLAVE>/archivos`). Al montar, la identidad de la
  app del cliente la descifra y se entrega a gocryptfs por la entrada estándar: nunca
  queda en disco ni en los argumentos del proceso.
- Destruir la clave `<CLAVE>-datos` al final de la retención vuelve ilegibles sus archivos.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

from app.plataforma import secretos

BASE_POR_DEFECTO = Path(os.environ.get("ARCHIVOS_BASE", "/srv/facturas"))
GOCRYPTFS = os.environ.get("GOCRYPTFS", "gocryptfs")


class ArchivosError(RuntimeError):
    pass


def rutas(clave: str, base: Path) -> tuple[Path, Path]:
    return base / clave / "archivos.cifrados", base / clave / "archivos"


def _credenciales_app(clave: str) -> tuple[str, str]:
    role, secret = os.environ.get("SECRETOS_APP_ROLE_ID"), os.environ.get("SECRETOS_APP_SECRET_ID")
    if not (role and secret):
        from app.plataforma import tenants

        env = tenants.leer_entorno(tenants.ruta_entorno(clave))
        role, secret = env.get("SECRETOS_APP_ROLE_ID"), env.get("SECRETOS_APP_SECRET_ID")
    if not (role and secret):
        raise ArchivosError(f"Faltan las credenciales de la app de {clave}")
    return role, secret


def _gocryptfs(*args: str, password: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([GOCRYPTFS, *args], input=password, capture_output=True)


def inicializar(clave: str, base: Path) -> dict:
    cifrados, visibles = rutas(clave, base)
    if (cifrados / "gocryptfs.conf").exists():
        raise ArchivosError(f"{cifrados} ya está inicializado")
    cifrados.mkdir(parents=True, exist_ok=True)
    visibles.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(48).encode()
    r = _gocryptfs("-init", "-q", "-passfile", "/dev/stdin", str(cifrados), password=password)
    if r.returncode != 0:
        raise ArchivosError(f"gocryptfs -init falló: {r.stderr.decode(errors='replace')[-300:]}")
    bao = secretos.plataforma()
    bao.escribir(f"tenants/{clave}/archivos", {"password_cifrada": bao.cifrar(f"{clave}-datos", password)})
    return {"cifrados": str(cifrados), "visibles": str(visibles)}


def montar(clave: str, base: Path) -> dict:
    cifrados, visibles = rutas(clave, base)
    visibles.mkdir(parents=True, exist_ok=True)
    if os.path.ismount(visibles):
        return {"visibles": str(visibles), "estado": "ya montado"}
    role, secret = _credenciales_app(clave)
    app = secretos.Bao().login_approle(role, secret)
    password = app.descifrar(f"{clave}-datos", app.leer(f"tenants/{clave}/archivos")["password_cifrada"])
    # -allow_other: el contenedor de la app (uid 10001) lee la vista; requiere user_allow_other en /etc/fuse.conf.
    r = _gocryptfs("-q", "-allow_other", "-passfile", "/dev/stdin", str(cifrados), str(visibles), password=password)
    if r.returncode != 0:
        raise ArchivosError(f"No se pudo montar: {r.stderr.decode(errors='replace')[-300:]}")
    return {"visibles": str(visibles), "estado": "montado"}


def desmontar(clave: str, base: Path) -> dict:
    _, visibles = rutas(clave, base)
    if not os.path.ismount(visibles):
        return {"estado": "no estaba montado"}
    r = subprocess.run(["fusermount3", "-u", str(visibles)], capture_output=True)
    if r.returncode != 0:
        r = subprocess.run(["fusermount", "-u", str(visibles)], capture_output=True)
    if r.returncode != 0:
        raise ArchivosError(f"No se pudo desmontar: {r.stderr.decode(errors='replace')[-300:]}")
    return {"estado": "desmontado"}


def probar(clave: str, base: Path) -> dict:
    """Inicializa en una carpeta de prueba, monta, escribe, comprueba el cifrado y vuelve a montar."""
    if base.exists():
        shutil.rmtree(base)
    resultado: dict = {}
    inicializar(clave, base)
    montar(clave, base)
    cifrados, visibles = rutas(clave, base)
    contenido = b"FACTURA-DE-PRUEBA RFC XAXX010101000 TOTAL 1234.56"
    (visibles / "factura-prueba.pdf").write_bytes(contenido)
    desmontar(clave, base)
    en_disco = [p for p in cifrados.rglob("*") if p.is_file()]
    resultado["vista_vacia_al_desmontar"] = not any(visibles.iterdir())
    resultado["nombre_visible_en_disco"] = any("factura-prueba" in p.name for p in en_disco)
    resultado["contenido_visible_en_disco"] = any(contenido in p.read_bytes() for p in en_disco)
    montar(clave, base)
    resultado["se_lee_tras_montar"] = (visibles / "factura-prueba.pdf").read_bytes() == contenido
    desmontar(clave, base)
    r = _gocryptfs("-q", "-passfile", "/dev/stdin", str(cifrados), str(visibles), password=b"contrasena-equivocada")
    resultado["contrasena_equivocada_rechazada"] = r.returncode != 0
    if r.returncode == 0:
        desmontar(clave, base)
    resultado["aprobado"] = (resultado["vista_vacia_al_desmontar"] and not resultado["nombre_visible_en_disco"]
                             and not resultado["contenido_visible_en_disco"] and resultado["se_lee_tras_montar"]
                             and resultado["contrasena_equivocada_rechazada"])
    return resultado


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.plataforma.archivos")
    sub = parser.add_subparsers(dest="comando", required=True)
    for nombre in ("inicializar", "montar", "desmontar", "probar"):
        p = sub.add_parser(nombre)
        p.add_argument("--clave", required=True)
        p.add_argument("--base", type=Path, default=BASE_POR_DEFECTO)
    args = parser.parse_args(argv)
    accion = {"inicializar": inicializar, "montar": montar, "desmontar": desmontar, "probar": probar}[args.comando]
    try:
        resultado = accion(args.clave.upper(), args.base)
        print(json.dumps(resultado, ensure_ascii=False))
        return 0 if resultado.get("aprobado", True) else 1
    except (ArchivosError, secretos.SecretosError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
