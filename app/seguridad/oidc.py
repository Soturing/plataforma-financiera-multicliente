"""Cliente OIDC del lado del servidor (patrón backend for frontend, D-021).

Flujo de código con PKCE y secreto de cliente. El navegador nunca recibe los
tokens del proveedor: el servidor los verifica, crea su propia sesión y los descarta.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import urlencode

import httpx
import jwt

from app.config import get_settings
from app.errors import DomainError

ROL_LLAVE_FISICA = "requiere-llave-fisica"
_ALGORITMOS = ["RS256", "ES256"]


@dataclass(frozen=True)
class IdentidadVerificada:
    subject: str
    correo: str | None
    nombre: str | None
    autenticado_en: datetime
    llave_fisica: bool
    idp_sid: str | None


def interna(url: str) -> str:
    """Reescribe una URL pública del proveedor a su dirección interna, si está configurada."""
    s = get_settings()
    if not s.oidc_url_interna:
        return url
    publica = s.oidc_issuer.split("/realms/", 1)[0]
    return url.replace(publica, s.oidc_url_interna.rstrip("/"), 1) if url.startswith(publica) else url


@lru_cache
def _descubrimiento(issuer: str) -> dict:
    r = httpx.get(interna(f"{issuer}/.well-known/openid-configuration"), timeout=15)
    r.raise_for_status()
    return r.json()


@lru_cache
def _jwks(jwks_uri: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_uri, cache_keys=True, lifespan=3600)


def nuevo_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def url_autorizacion(*, state: str, nonce: str, challenge: str, reautenticar: bool, correo: str | None = None) -> str:
    s = get_settings()
    params = {
        "client_id": s.oidc_client_id,
        "redirect_uri": f"{s.app_url}/auth/callback",
        "response_type": "code",
        "scope": "openid",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if reautenticar:
        # Fuerza una ceremonia nueva aunque exista sesión en el proveedor (prueba técnica, punto 3).
        params.update({"prompt": "login", "max_age": "0"})
    if correo:
        params["login_hint"] = correo
    return f"{_descubrimiento(s.oidc_issuer)['authorization_endpoint']}?{urlencode(params)}"


def canjear_codigo(code: str, verifier: str, nonce: str) -> IdentidadVerificada:
    s = get_settings()
    if not s.oidc_client_secret:
        raise DomainError("Falta FACTURAS_OIDC_CLIENT_SECRET.", 503)
    meta = _descubrimiento(s.oidc_issuer)
    r = httpx.post(
        interna(meta["token_endpoint"]),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": f"{s.app_url}/auth/callback",
            "code_verifier": verifier,
            "client_id": s.oidc_client_id,
            "client_secret": s.oidc_client_secret,
        },
        timeout=30,
    )
    if r.status_code != 200:
        raise DomainError("El proveedor de identidad rechazó el inicio de sesión.", 401)
    tokens = r.json()
    id_token = verificar_token(tokens["id_token"], audiencia=s.oidc_client_id)
    if id_token.get("nonce") != nonce:
        raise DomainError("Respuesta de inicio de sesión inválida.", 401)
    acceso = verificar_token(tokens["access_token"], audiencia=None)
    if acceso.get("sub") != id_token["sub"]:
        raise DomainError("Respuesta de inicio de sesión inválida.", 401)
    roles = acceso.get("realm_access", {}).get("roles", [])
    return IdentidadVerificada(
        subject=id_token["sub"],
        correo=id_token.get("email"),
        nombre=id_token.get("name") or id_token.get("preferred_username"),
        autenticado_en=datetime.fromtimestamp(id_token["auth_time"], tz=timezone.utc),
        llave_fisica=ROL_LLAVE_FISICA in roles,
        idp_sid=id_token.get("sid"),
    )


def verificar_token(token: str, *, audiencia: str | None) -> dict:
    s = get_settings()
    meta = _descubrimiento(s.oidc_issuer)
    clave = _jwks(interna(meta["jwks_uri"])).get_signing_key_from_jwt(token)
    opciones = {"require": ["exp", "iat", "sub", "iss"], "verify_aud": audiencia is not None}
    datos = jwt.decode(
        token, clave.key, algorithms=_ALGORITMOS, audience=audiencia, issuer=meta["issuer"],
        options=opciones, leeway=30,
    )
    if audiencia is None and datos.get("azp") != s.oidc_client_id:
        raise DomainError("Token emitido para otro cliente.", 401)
    if datos["iat"] > time.time() + 60:
        raise DomainError("Token con fecha futura.", 401)
    return datos


def url_cierre_proveedor() -> str:
    s = get_settings()
    meta = _descubrimiento(s.oidc_issuer)
    return f"{meta['end_session_endpoint']}?" + urlencode(
        {"client_id": s.oidc_client_id, "post_logout_redirect_uri": f"{s.app_url}/auth/salida"}
    )
