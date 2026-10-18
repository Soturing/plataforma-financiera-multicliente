"""Cliente de pruebas para el proveedor de identidad local (perfil `identidad`).

Reúne tres piezas que las pruebas de integración necesitan:

- `AdminKeycloak`: administración mediante la cuenta de instalación del entorno local;
- `CorreoPruebas`: lectura de los correos capturados por Mailpit;
- `Navegador`: recorre las páginas de acceso de Keycloak como lo haría un
  navegador, delegando las ceremonias WebAuthn en un `AutenticadorSoftware`.

Sólo funciona contra el entorno local de desarrollo; nunca contra producción.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
import jwt

from autenticador_software import AutenticadorSoftware, b64url, b64url_decode

RAIZ = Path(__file__).resolve().parents[2]
REALM = "facturas"
CLIENT_ID = "facturas-app"


def configuracion() -> dict[str, str]:
    """Variables del entorno, completadas con el `.env` local si existe."""
    valores: dict[str, str] = {}
    env_file = RAIZ / ".env"
    if env_file.exists():
        for linea in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.lstrip().startswith("#"):
                clave, valor = linea.split("=", 1)
                valores[clave.strip()] = valor.strip()
    valores.update({k: v for k, v in os.environ.items() if k.startswith(("IDENTIDAD_", "FACTURAS_", "CORREO_"))})
    valores.setdefault("IDENTIDAD_PORT", "8180")
    valores.setdefault("CORREO_PRUEBAS_PORT", "8025")
    valores.setdefault("FACTURAS_APP_URL", "http://localhost:8000")
    valores["IDENTIDAD_URL"] = f"http://localhost:{valores['IDENTIDAD_PORT']}"
    valores["CORREO_URL"] = f"http://localhost:{valores['CORREO_PRUEBAS_PORT']}"
    return valores


def disponible() -> bool:
    try:
        url = configuracion()["IDENTIDAD_URL"]
        return httpx.get(f"{url}/realms/{REALM}/.well-known/openid-configuration", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


# --------------------------------------------------------------------------- #
# Administración


class AdminKeycloak:
    def __init__(self, conf: dict[str, str]) -> None:
        self.base = conf["IDENTIDAD_URL"]
        self._usuario = conf["IDENTIDAD_ADMIN_USER"]
        self._clave = conf["IDENTIDAD_ADMIN_PASSWORD"]
        self._http = httpx.Client(base_url=f"{self.base}/admin/realms/{REALM}", timeout=90)

    def _token(self) -> str:
        r = httpx.post(
            f"{self.base}/realms/master/protocol/openid-connect/token",
            data={"grant_type": "password", "client_id": "admin-cli", "username": self._usuario, "password": self._clave},
            timeout=90,
        )
        r.raise_for_status()
        return r.json()["access_token"]

    def _req(self, metodo: str, ruta: str, **kw) -> httpx.Response:
        r = self._http.request(metodo, ruta, headers={"Authorization": f"Bearer {self._token()}"}, **kw)
        r.raise_for_status()
        return r

    def crear_usuario(self, correo: str, *, rol_global: bool = False) -> str:
        r = self._req("POST", "/users", json={"username": correo, "email": correo, "enabled": True, "emailVerified": True})
        user_id = r.headers["Location"].rsplit("/", 1)[1]
        if rol_global:
            rol = self._req("GET", "/roles/requiere-llave-fisica").json()
            self._req("POST", f"/users/{user_id}/role-mappings/realm", json=[rol])
        return user_id

    def borrar_usuario(self, user_id: str) -> None:
        self._req("DELETE", f"/users/{user_id}")

    def enviar_acciones(self, user_id: str, acciones: list[str]) -> None:
        """Invitación: enlace de un solo uso por correo con las acciones requeridas."""
        self._req(
            "PUT",
            f"/users/{user_id}/execute-actions-email",
            params={"client_id": CLIENT_ID, "redirect_uri": f"{configuracion()['FACTURAS_APP_URL']}/auth/callback", "lifespan": 86400},
            json=acciones,
        )

    def credenciales(self, user_id: str) -> list[dict]:
        return self._req("GET", f"/users/{user_id}/credentials").json()

    def sesiones(self, user_id: str) -> list[dict]:
        return self._req("GET", f"/users/{user_id}/sessions").json()

    def cerrar_sesiones(self, user_id: str) -> None:
        self._req("POST", f"/users/{user_id}/logout")

    def realm(self) -> dict:
        return self._req("GET", "").json()

    def actualizar_realm(self, cambios: dict) -> None:
        self._req("PUT", "", json=cambios)

    def eventos(self, user_id: str) -> list[dict]:
        return self._req("GET", "/events", params={"user": user_id, "max": 100}).json()


# --------------------------------------------------------------------------- #
# Correo capturado


class CorreoPruebas:
    def __init__(self, conf: dict[str, str]) -> None:
        self._http = httpx.Client(base_url=f"{conf['CORREO_URL']}/api/v1", timeout=30)

    def enlace_para(self, correo: str, *, espera: float = 20.0) -> str:
        limite = time.monotonic() + espera
        while time.monotonic() < limite:
            mensajes = self._http.get("/search", params={"query": f"to:{correo}"}).json().get("messages", [])
            if mensajes:
                texto = self._http.get(f"/message/{mensajes[0]['ID']}").json()["Text"]
                enlace = re.search(r"https?://\S+action-token\S+", texto)
                if enlace:
                    return enlace.group(0)
            time.sleep(0.5)
        raise TimeoutError(f"No llegó correo para {correo}")


# --------------------------------------------------------------------------- #
# Navegador mínimo


class _Formularios(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.formularios: list[dict] = []
        self._actual: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self._actual = {"id": a.get("id"), "action": html.unescape(a.get("action") or ""), "campos": {}}
            self.formularios.append(self._actual)
        elif tag in ("input", "button") and self._actual is not None and a.get("name"):
            self._actual["campos"].setdefault(a["name"], a.get("value") or "")

    def handle_endtag(self, tag):
        if tag == "form":
            self._actual = None


@dataclass
class Pagina:
    url: str
    status: int
    texto: str
    formularios: list[dict] = field(default_factory=list)

    def formulario(self, *, id: str | None = None, con_campo: str | None = None) -> dict:
        for f in self.formularios:
            if (id and f["id"] == id) or (con_campo and con_campo in f["campos"]):
                return f
        raise LookupError(f"Formulario no encontrado (id={id}, campo={con_campo}) en {self.url}\n{self.resumen()}")

    def resumen(self) -> str:
        titulo = re.search(r"<title>(.*?)</title>", self.texto, re.S)
        error = re.search(r'id="input-error[^"]*"[^>]*>(.*?)<', self.texto, re.S) or re.search(
            r'class="[^"]*alert[^"]*"[^>]*>.*?<span[^>]*kc-feedback-text[^>]*>(.*?)</span>', self.texto, re.S
        )
        return f"[{self.status}] {titulo.group(1).strip() if titulo else '?'} | {error.group(1).strip() if error else ''}"


@dataclass
class ResultadoAcceso:
    code: str | None
    pagina: Pagina | None
    tokens: dict | None = None
    id_token: dict | None = None


class Navegador:
    """Sesión de navegador: cookies propias y un autenticador WebAuthn."""

    def __init__(self, conf: dict[str, str], autenticador: AutenticadorSoftware | None = None) -> None:
        self.conf = conf
        self.base = conf["IDENTIDAD_URL"]
        self.redirect_uri = f"{conf['FACTURAS_APP_URL']}/auth/callback"
        self.http = httpx.Client(timeout=90, follow_redirects=False)
        self.autenticador = autenticador or AutenticadorSoftware(origin=self.base)
        self.rp_id = urlparse(self.base).hostname

    # -- navegación -------------------------------------------------------- #

    def _cookies_localhost(self) -> None:
        # Los navegadores envían cookies `Secure` a http://localhost (contexto
        # seguro); http.cookiejar no. Sólo afecta al entorno local de pruebas.
        for cookie in self.http.cookies.jar:
            cookie.secure = False

    def _seguir(self, r: httpx.Response) -> Pagina | str:
        """Sigue redirecciones; devuelve la página final o el `code` si llega al callback."""
        self._cookies_localhost()
        while r.is_redirect:
            destino = urljoin(str(r.url), r.headers["Location"])
            if destino.startswith(self.redirect_uri):
                q = parse_qs(urlparse(destino).query)
                if "error" in q:
                    raise PermissionError(f"Callback con error: {q}")
                return q["code"][0]
            r = self.http.get(destino)
            self._cookies_localhost()
        parser = _Formularios()
        parser.feed(r.text)
        return Pagina(str(r.url), r.status_code, r.text, parser.formularios)

    def ir(self, url: str) -> Pagina | str:
        return self._seguir(self.http.get(url))

    def enviar(self, pagina: Pagina, formulario: dict, campos: dict[str, str]) -> Pagina | str:
        datos = dict(formulario["campos"])
        datos.update(campos)
        accion = urljoin(pagina.url, formulario["action"]) if formulario["action"] else pagina.url
        return self._seguir(self.http.post(accion, data=datos))

    # -- OIDC -------------------------------------------------------------- #

    def url_autorizacion(self, **extra: str) -> tuple[str, str]:
        verifier = secrets.token_urlsafe(48)
        challenge = b64url(hashlib.sha256(verifier.encode()).digest())
        params = {
            "client_id": CLIENT_ID,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid",
            "state": secrets.token_urlsafe(16),
            "nonce": secrets.token_urlsafe(16),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            **extra,
        }
        url = f"{self.base}/realms/{REALM}/protocol/openid-connect/auth?" + httpx.QueryParams(params).__str__()
        return url, verifier

    def canjear(self, code: str, verifier: str) -> tuple[dict, dict]:
        r = httpx.post(
            f"{self.base}/realms/{REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "code_verifier": verifier,
                "client_id": CLIENT_ID,
                "client_secret": self.conf["FACTURAS_OIDC_CLIENT_SECRET"],
            },
            timeout=90,
        )
        r.raise_for_status()
        tokens = r.json()
        jwks = jwt.PyJWKClient(f"{self.base}/realms/{REALM}/protocol/openid-connect/certs")
        clave = jwks.get_signing_key_from_jwt(tokens["id_token"])
        id_token = jwt.decode(
            tokens["id_token"], clave.key, algorithms=["RS256"], audience=CLIENT_ID, issuer=f"{self.base}/realms/{REALM}"
        )
        return tokens, id_token

    # -- ceremonias -------------------------------------------------------- #

    def iniciar_sesion(self, correo: str, *, usar: str = "webauthn", codigo: str | None = None, **extra: str) -> ResultadoAcceso:
        """Recorre el flujo de acceso. `usar`: 'webauthn' o 'codigo' (recuperación)."""
        url, verifier = self.url_autorizacion(**extra)
        paso = self.ir(url)
        credencial_enviada = False
        for _ in range(8):
            if isinstance(paso, str):
                tokens, id_token = self.canjear(paso, verifier)
                return ResultadoAcceso(paso, None, tokens, id_token)
            if credencial_enviada and _campos(paso) & {"recoveryCodeInput", "authenticatorData"}:
                # Keycloak rechazó la credencial y vuelve a pedirla: un intento por acceso,
                # como una persona; reintentar al instante dispara la detección de intentos rápidos.
                return ResultadoAcceso(None, paso)
            if "username" in _campos(paso):
                paso = self.enviar(paso, paso.formulario(con_campo="username"), {"username": correo})
            elif usar == "codigo" and "recoveryCodeInput" in _campos(paso):
                credencial_enviada = True
                paso = self.enviar(paso, paso.formulario(con_campo="recoveryCodeInput"), {"recoveryCodeInput": codigo or ""})
            elif usar == "codigo" and "tryAnotherWay" in _campos(paso):
                paso = self.enviar(paso, paso.formulario(con_campo="tryAnotherWay"), {})
            elif usar == "codigo" and "authenticationExecution" in _campos(paso):
                ejecucion = _opcion_recuperacion(paso)
                paso = self.enviar(paso, paso.formulario(con_campo="authenticationExecution"), {"authenticationExecution": ejecucion})
            elif "authenticatorData" in _campos(paso):
                credencial_enviada = True
                paso = self.enviar(paso, paso.formulario(con_campo="authenticatorData"), self._firmar(paso))
            else:
                return ResultadoAcceso(None, paso)
        return ResultadoAcceso(None, paso if isinstance(paso, Pagina) else None)

    def completar_invitacion(self, enlace: str, *, etiqueta: str = "dispositivo de prueba") -> Pagina | str:
        """Abre el enlace del correo y registra el autenticador (y códigos si se piden)."""
        paso = self.ir(enlace)
        for _ in range(8):
            if isinstance(paso, str):
                return paso
            campos = _campos(paso)
            if "attestationObject" in campos:
                paso = self.enviar(paso, paso.formulario(con_campo="attestationObject"), self._registrar(paso, etiqueta))
            elif "generatedRecoveryAuthnCodes" in campos:
                self.codigos_recuperacion = _codigos(paso)
                paso = self.enviar(paso, paso.formulario(con_campo="generatedRecoveryAuthnCodes"), {})
            elif _enlace_continuar(paso):
                paso = self.ir(_enlace_continuar(paso))
            else:
                return paso
        return paso

    def _opciones(self, pagina: Pagina) -> dict:
        return _opciones_webauthn(pagina.texto)

    def _registrar(self, pagina: Pagina, etiqueta: str) -> dict[str, str]:
        o = self._opciones(pagina)
        r = self.autenticador.crear(
            challenge=b64url_decode(o["challenge"]),
            rp_id=o.get("rpId") or self.rp_id,
            user_handle=b64url_decode(o["userid"]) if o.get("userid") else secrets.token_bytes(16),
        )
        return {**r, "authenticatorLabel": etiqueta, "transports": "usb", "authenticatorAttachment": "cross-platform"}

    def _firmar(self, pagina: Pagina) -> dict[str, str]:
        o = self._opciones(pagina)
        permitidas = [b64url_decode(c) for c in o.get("allowCredentials", [])]
        return self.autenticador.obtener(
            challenge=b64url_decode(o["challenge"]), rp_id=o.get("rpId") or self.rp_id, permitidas=permitidas
        )


def _campos(pagina: Pagina) -> set[str]:
    return {nombre for f in pagina.formularios for nombre in f["campos"]}


def _opcion_recuperacion(pagina: Pagina) -> str:
    """En la pantalla 'Probar otra manera', la ejecución cuyo título es el código de recuperación."""
    opciones = re.findall(
        r'name="authenticationExecution" value="([^"]+)".*?select-auth-box-headline[^>]*>\s*(.*?)\s*<', pagina.texto, re.S
    )
    for ejecucion, titulo in opciones:
        if re.search(r"recupera|recovery", titulo, re.I):
            return ejecucion
    raise LookupError(f"Sin opción de código de recuperación: {opciones}")


def _enlace_continuar(pagina: Pagina) -> str | None:
    m = re.search(r'href="([^"]*(?:action-token|login-actions)[^"]*)"', pagina.texto)
    return urljoin(pagina.url, html.unescape(m.group(1))) if m else None


def _codigos(pagina: Pagina) -> list[str]:
    return re.findall(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}\b", pagina.texto)


def _opciones_webauthn(texto: str) -> dict:
    """Extrae challenge, rpId, userid y credenciales permitidas del HTML de Keycloak."""
    opciones: dict = {}
    for clave in ("challenge", "rpId", "userid", "username"):
        m = re.search(rf'["\']?{clave}["\']?\s*[:=]\s*["\']([^"\']+)["\']', texto)
        if m:
            opciones[clave] = m.group(1)
    permitidas = re.findall(r'name="authn_use_chk"[^>]*value="([^"]+)"', texto)
    if not permitidas:
        m = re.search(r'allowCredentials["\']?\s*[:=]\s*(\[.*?\])', texto, re.S)
        if m:
            try:
                permitidas = [c["id"] if isinstance(c, dict) else c for c in json.loads(m.group(1))]
            except json.JSONDecodeError:
                permitidas = []
    opciones["allowCredentials"] = permitidas
    return opciones


def decodificar_sin_verificar(token: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
