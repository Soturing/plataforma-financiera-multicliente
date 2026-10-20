"""Gestor de secretos y claves por cliente con OpenBao (D-025, arquitectura-aislamiento §10).

Uso:
    python -m app.plataforma.secretos inicializar [--desarrollo]
    python -m app.plataforma.secretos abrir [--desde-archivo]
    python -m app.plataforma.secretos estado

Diseño:
- 3 llaves de desbloqueo, se necesitan 2 (Shamir). Tras cada reinicio OpenBao queda
  sellado y la app no obtiene secretos hasta que el director lo abre.
- El token raíz se revoca al terminar la inicialización. El aprovisionamiento usa un
  token con la política `plataforma` (alta de clientes, rotación); nunca la app.
- Cada cliente tiene dos claves Transit (`<clave>-datos`, `<clave>-respaldos`), no
  exportables y sin borrado permitido salvo en el procedimiento de baja.
- Cada cliente tiene dos identidades AppRole: `<clave>-app` y `<clave>-respaldos`. Cada
  una sólo puede leer sus secretos y usar su clave.
- Bitácora de auditoría de OpenBao activa: registra cada uso de claves y secretos.

En `--desarrollo`, las llaves de desbloqueo y el token de plataforma se guardan en
`config/secretos/private/` (ignorado por git) para poder reiniciar sin intervención.
En producción se entregan una sola vez por pantalla y NUNCA se guardan en el servidor.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import secrets
import sys
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parents[2]
PRIVADO = RAIZ / "config" / "secretos" / "private"
URL_POR_DEFECTO = "http://127.0.0.1:8200"


class SecretosError(RuntimeError):
    pass


class Bao:
    def __init__(self, url: str | None = None, token: str | None = None) -> None:
        self.url = (url or os.environ.get("SECRETOS_URL") or URL_POR_DEFECTO).rstrip("/")
        self.token = token

    def _req(self, metodo: str, ruta: str, *, json_body: dict | None = None, esperado=(200, 204)) -> dict:
        headers = {"X-Vault-Token": self.token} if self.token else {}
        r = httpx.request(metodo, f"{self.url}/v1/{ruta}", headers=headers, json=json_body, timeout=20)
        if r.status_code not in esperado:
            errores = r.json().get("errors") if r.headers.get("content-type", "").startswith("application/json") else r.text
            raise SecretosError(f"OpenBao {metodo} {ruta}: {r.status_code} {errores}")
        return r.json() if r.content else {}

    # -- estado ------------------------------------------------------------ #
    def estado(self) -> dict:
        return self._req("GET", "sys/seal-status")

    def abrir(self, llaves: list[str]) -> dict:
        resultado = {}
        for llave in llaves:
            resultado = self._req("POST", "sys/unseal", json_body={"key": llave})
            if not resultado.get("sealed"):
                break
        return resultado

    # -- identidades ------------------------------------------------------- #
    def login_approle(self, role_id: str, secret_id: str) -> Bao:
        datos = self._req("POST", "auth/approle/login", json_body={"role_id": role_id, "secret_id": secret_id})
        return Bao(self.url, datos["auth"]["client_token"])

    # -- KV ---------------------------------------------------------------- #
    def leer(self, ruta: str) -> dict:
        return self._req("GET", f"secret/data/{ruta}")["data"]["data"]

    def escribir(self, ruta: str, datos: dict) -> None:
        self._req("POST", f"secret/data/{ruta}", json_body={"data": datos})

    # -- Transit ----------------------------------------------------------- #
    def cifrar(self, clave: str, texto: bytes) -> str:
        datos = self._req("POST", f"transit/encrypt/{clave}", json_body={"plaintext": base64.b64encode(texto).decode()})
        return datos["data"]["ciphertext"]

    def descifrar(self, clave: str, cifrado: str) -> bytes:
        datos = self._req("POST", f"transit/decrypt/{clave}", json_body={"ciphertext": cifrado})
        return base64.b64decode(datos["data"]["plaintext"])

    def rotar(self, clave: str) -> int:
        self._req("POST", f"transit/keys/{clave}/rotate")
        return self._req("GET", f"transit/keys/{clave}")["data"]["latest_version"]


# --------------------------------------------------------------------------- #
# Inicialización


POLITICA_PLATAFORMA = """
# Aprovisionamiento de clientes: claves, políticas, identidades y secretos por cliente.
path "sys/policies/acl/tenant-*" { capabilities = ["create", "read", "update"] }
path "auth/approle/role/*" { capabilities = ["create", "read", "update"] }
path "auth/approle/role/+/secret-id" { capabilities = ["create", "update"] }
path "transit/keys/*" { capabilities = ["create", "read", "update"] }
path "transit/keys/+/rotate" { capabilities = ["update"] }
path "transit/encrypt/*" { capabilities = ["update"] }
path "secret/data/tenants/*" { capabilities = ["create", "read", "update"] }
path "secret/data/plataforma/*" { capabilities = ["create", "read", "update"] }
path "secret/metadata/tenants/*" { capabilities = ["read", "list"] }
path "sys/seal-status" { capabilities = ["read"] }
# Token raíz temporal: además de este token exige 2 de 3 llaves de desbloqueo.
path "sys/generate-root-token/*" { capabilities = ["create", "read", "update", "delete", "sudo"] }
"""


def politica_app(clave: str) -> str:
    return f"""
path "secret/data/tenants/{clave}/app" {{ capabilities = ["read"] }}
path "secret/data/tenants/{clave}/archivos" {{ capabilities = ["read"] }}
path "secret/data/plataforma/app" {{ capabilities = ["read"] }}
path "transit/encrypt/{clave}-datos" {{ capabilities = ["update"] }}
path "transit/decrypt/{clave}-datos" {{ capabilities = ["update"] }}
path "transit/datakey/plaintext/{clave}-datos" {{ capabilities = ["update"] }}
"""


def politica_respaldos(clave: str) -> str:
    return f"""
path "secret/data/tenants/{clave}/respaldos" {{ capabilities = ["read"] }}
path "transit/decrypt/{clave}-respaldos" {{ capabilities = ["update"] }}
"""


def inicializar(*, desarrollo: bool) -> dict:
    bao = Bao()
    if bao.estado()["initialized"]:
        raise SecretosError("OpenBao ya está inicializado.")
    init = bao._req("POST", "sys/init", json_body={"secret_shares": 3, "secret_threshold": 2})  # nosec B105
    # Motivo: nombres de parámetros de la API de OpenBao, no contraseñas
    llaves, raiz = init["keys_base64"], init["root_token"]
    # Las llaves se entregan antes de cualquier otro paso: si algo falla después, no se pierden.
    if desarrollo:
        PRIVADO.mkdir(parents=True, exist_ok=True)
        (PRIVADO / "llaves-desbloqueo.json").write_text(json.dumps(llaves), encoding="utf-8")
    else:
        print("Llaves de desbloqueo (guárdelas por separado; se necesitan 2 de 3):")
        for n, llave in enumerate(llaves, 1):
            print(f"  Llave {n}: {llave}")
    bao.abrir(llaves[:2])
    root = Bao(bao.url, raiz)
    # La auditoría se declara en openbao.hcl (OpenBao no la permite por API).
    root._req("POST", "sys/mounts/transit", json_body={"type": "transit"})
    root._req("POST", "sys/mounts/secret", json_body={"type": "kv", "options": {"version": "2"}})
    root._req("POST", "sys/auth/approle", json_body={"type": "approle"})
    root._req("POST", "sys/policies/acl/plataforma", json_body={"policy": POLITICA_PLATAFORMA})
    plataforma = root._req("POST", "auth/token/create-orphan", json_body={
        "policies": ["plataforma"], "period": "720h", "display_name": "plataforma", "no_default_policy": False,
    })["auth"]["client_token"]
    root._req("POST", "auth/token/revoke-self")  # no queda token raíz vivo
    if desarrollo:
        (PRIVADO / "token-plataforma").write_text(plataforma, encoding="utf-8")
    return {"llaves": llaves, "token_plataforma": plataforma}


def raiz_temporal(llaves: list[str], *, ruta: str = "sys/generate-root-token", token: str | None = None) -> Bao:
    """Token raíz temporal: token de plataforma + 2 de 3 llaves. Debe revocarse al terminar.

    `ruta="sys/generate-root"` (sin autenticación) sólo sirve si el listener lo habilita
    temporalmente: procedimiento de recuperación documentado por OpenBao."""
    bao = Bao(token=token if token is not None else token_plataforma())
    def datos(r: dict) -> dict:  # el endpoint autenticado responde dentro de "data"
        return r.get("data") or r

    if datos(bao._req("GET", f"{ruta}/attempt")).get("started"):
        bao._req("DELETE", f"{ruta}/attempt")  # intento abandonado: se cancela y se reinicia
    intento = datos(bao._req("POST", f"{ruta}/attempt", json_body={}))
    nonce, otp = intento["nonce"], intento["otp"]
    resultado = {}
    for llave in llaves:
        resultado = datos(bao._req("POST", f"{ruta}/update", json_body={"key": llave, "nonce": nonce}))
        if resultado.get("complete"):
            break
    if not resultado.get("complete"):
        raise SecretosError("Se necesitan 2 llaves de desbloqueo válidas.")
    cifrado = base64.b64decode(resultado["encoded_token"] + "=" * (-len(resultado["encoded_token"]) % 4))
    token = bytes(a ^ b for a, b in zip(cifrado, otp.encode())).decode()
    return Bao(bao.url, token)


def actualizar_politicas(llaves: list[str], *, ruta: str = "sys/generate-root-token") -> None:
    """Aplica la política `plataforma` vigente en el código y revoca el token raíz temporal."""
    root = raiz_temporal(llaves, ruta=ruta, token=None if ruta == "sys/generate-root-token" else "")
    try:
        root._req("POST", "sys/policies/acl/plataforma", json_body={"policy": POLITICA_PLATAFORMA})
    finally:
        root._req("POST", "auth/token/revoke-self")


def token_plataforma() -> str:
    token = os.environ.get("SECRETOS_TOKEN")
    archivo = PRIVADO / "token-plataforma"
    if not token and archivo.exists():
        token = archivo.read_text(encoding="utf-8").strip()
    if not token:
        raise SecretosError("Falta el token de plataforma (SECRETOS_TOKEN).")
    return token


def plataforma() -> Bao:
    bao = Bao(token=token_plataforma())
    if bao.estado()["sealed"]:
        raise SecretosError("OpenBao está sellado: ábralo con `python -m app.plataforma.secretos abrir`.")
    return bao


# --------------------------------------------------------------------------- #
# Clientes


def preparar_cliente(clave: str, *, secretos_base: dict, secretos_app: dict, respaldos: dict) -> dict:
    """Claves, políticas, identidades y secretos de un cliente. Idempotente."""
    bao = plataforma()
    for sufijo in ("datos", "respaldos"):
        bao._req("POST", f"transit/keys/{clave}-{sufijo}", json_body={"type": "aes256-gcm96", "exportable": False})
    bao._req("POST", f"sys/policies/acl/tenant-{clave}-app", json_body={"policy": politica_app(clave)})
    bao._req("POST", f"sys/policies/acl/tenant-{clave}-respaldos", json_body={"policy": politica_respaldos(clave)})
    identidades = {}
    for uso in ("app", "respaldos"):
        rol = f"{clave}-{uso}"
        bao._req("POST", f"auth/approle/role/{rol}", json_body={
            "token_policies": [f"tenant-{clave}-{uso}"], "token_ttl": "1h", "token_max_ttl": "4h",  # nosec B105
            # Motivo: nombres de parámetros de la API de OpenBao, no contraseñas
            "secret_id_ttl": "0", "token_bound_cidrs": ["127.0.0.1/32", "172.16.0.0/12"],  # nosec B105
            # Motivo: nombres de parámetros de la API de OpenBao, no contraseñas
            "secret_id_bound_cidrs": ["127.0.0.1/32", "172.16.0.0/12"],
        })
        role_id = bao._req("GET", f"auth/approle/role/{rol}/role-id")["data"]["role_id"]
        secret_id = bao._req("POST", f"auth/approle/role/{rol}/secret-id")["data"]["secret_id"]
        identidades[uso] = {"role_id": role_id, "secret_id": secret_id}
    bao.escribir(f"tenants/{clave}/base", secretos_base)
    bao.escribir(f"tenants/{clave}/app", secretos_app)
    # La contraseña del repositorio de respaldos sólo existe cifrada con la clave de
    # respaldos del cliente: destruir esa clave vuelve ilegibles sus respaldos (§10).
    try:  # repetir el alta nunca cambia la contraseña del repositorio (dejaría ilegibles los respaldos)
        existente = bao.leer(f"tenants/{clave}/respaldos").get("password_repositorio_cifrada")
    except SecretosError:
        existente = None
    password_repo = respaldos.pop("password_repositorio", None) or secrets.token_urlsafe(48)
    respaldos["password_repositorio_cifrada"] = existente or bao.cifrar(f"{clave}-respaldos", password_repo.encode())
    bao.escribir(f"tenants/{clave}/respaldos", respaldos)
    return identidades


def leer_base(clave: str) -> dict:
    return plataforma().leer(f"tenants/{clave}/base")


def secretos_app(clave: str, role_id: str, secret_id: str) -> dict:
    """Lo que la app de un cliente obtiene con su propia identidad (no con la de plataforma)."""
    return Bao().login_approle(role_id, secret_id).leer(f"tenants/{clave}/app")


CLAVES_PLATAFORMA = (
    "FACTURAS_CONTROL_DATABASE_URL", "FACTURAS_OIDC_CLIENT_SECRET", "FACTURAS_IDP_ADMIN_CLIENT_SECRET",
    "FACTURAS_SMTP_USUARIO", "FACTURAS_SMTP_PASSWORD",
)


def guardar_plataforma(valores: dict[str, str]) -> list[str]:
    """Secretos compartidos que necesita la app de cada cliente (plano de control, OIDC, SMTP)."""
    datos = {k: v for k, v in valores.items() if k in CLAVES_PLATAFORMA and v}
    plataforma().escribir("plataforma/app", datos)
    return sorted(datos)


def secretos_arranque(clave: str, role_id: str, secret_id: str) -> dict[str, str]:
    """Todo lo que el contenedor de la app necesita, con la identidad de la app del cliente."""
    bao = Bao().login_approle(role_id, secret_id)
    propios = bao.leer(f"tenants/{clave}/app")
    try:
        compartidos = bao.leer("plataforma/app")
    except SecretosError:
        compartidos = {}
    return {**compartidos, "FACTURAS_DATABASE_URL": propios["database_url"]}


def secretos_respaldos(clave: str, role_id: str, secret_id: str) -> dict:
    bao = Bao().login_approle(role_id, secret_id)
    datos = bao.leer(f"tenants/{clave}/respaldos")
    datos["password_repositorio"] = bao.descifrar(f"{clave}-respaldos", datos.pop("password_repositorio_cifrada")).decode()
    return datos


# --------------------------------------------------------------------------- #
# CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.plataforma.secretos")
    sub = parser.add_subparsers(dest="comando", required=True)
    i = sub.add_parser("inicializar", help="Inicializa OpenBao (una sola vez)")
    i.add_argument("--desarrollo", action="store_true", help="Guarda llaves y token en config/secretos/private (sólo local)")
    a = sub.add_parser("abrir", help="Desbloquea OpenBao tras un reinicio (2 de 3 llaves)")
    a.add_argument("--desde-archivo", action="store_true", help="Lee las llaves de config/secretos/private (sólo local)")
    sub.add_parser("estado", help="Muestra si OpenBao está inicializado y abierto")
    p = sub.add_parser("actualizar-politicas", help="Aplica la política de plataforma (token raíz temporal con 2 llaves)")
    p.add_argument("--desde-archivo", action="store_true", help="Lee las llaves de config/secretos/private (sólo local)")
    p.add_argument("--recuperacion", action="store_true",
                   help="Usa el endpoint sin autenticación (sólo con el listener habilitado temporalmente)")
    g = sub.add_parser("guardar-plataforma", help="Copia a OpenBao los secretos compartidos de un archivo .env")
    g.add_argument("--desde", default=".env")
    r = sub.add_parser("rotar", help="Rota la clave de un cliente (las versiones anteriores siguen descifrando)")
    r.add_argument("--clave", required=True)
    r.add_argument("--uso", choices=["datos", "respaldos"], required=True)
    args = parser.parse_args(argv)
    try:
        if args.comando == "inicializar":
            resultado = inicializar(desarrollo=args.desarrollo)
            print("OpenBao inicializado.")
            if not args.desarrollo:
                print(f"Token de plataforma (aprovisionamiento): {resultado['token_plataforma']}")
            print("El token raíz ya fue revocado." + (" Copia local en config/secretos/private/." if args.desarrollo else ""))
        elif args.comando == "abrir":
            if args.desde_archivo:
                llaves = json.loads((PRIVADO / "llaves-desbloqueo.json").read_text(encoding="utf-8"))[:2]
            else:
                llaves = [getpass.getpass(f"Llave de desbloqueo {n} de 2: ") for n in (1, 2)]
            estado = Bao().abrir(llaves)
            print("Abierto" if not estado.get("sealed") else f"Sigue sellado ({estado.get('progress')}/{estado.get('t')})")
        elif args.comando == "actualizar-politicas":
            if args.desde_archivo:
                llaves = json.loads((PRIVADO / "llaves-desbloqueo.json").read_text(encoding="utf-8"))[:2]
            else:
                llaves = [getpass.getpass(f"Llave de desbloqueo {n} de 2: ") for n in (1, 2)]
            actualizar_politicas(llaves, ruta="sys/generate-root" if args.recuperacion else "sys/generate-root-token")
            print("Política de plataforma actualizada; el token raíz temporal fue revocado.")
        elif args.comando == "guardar-plataforma":
            valores = {}
            for linea in Path(args.desde).read_text(encoding="utf-8").splitlines():
                if "=" in linea and not linea.lstrip().startswith("#"):
                    k, v = linea.split("=", 1)
                    valores[k.strip()] = v.strip()
            print("Guardados en OpenBao:", guardar_plataforma(valores))
        elif args.comando == "rotar":
            print(f"Nueva versión de {args.clave}-{args.uso}: {plataforma().rotar(f'{args.clave}-{args.uso}')}")
        else:
            e = Bao().estado()
            print({"inicializado": e["initialized"], "sellado": e["sealed"], "version": e.get("version")})
        return 0
    except SecretosError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
