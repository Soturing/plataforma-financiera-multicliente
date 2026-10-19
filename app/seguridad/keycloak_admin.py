"""Operaciones de administración en Keycloak con la cuenta de servicio `facturas-control`.

Sólo gestiona usuarios del realm (crear, invitar, deshabilitar, cerrar sesiones).
Nunca maneja contraseñas: el alta de autenticadores ocurre en el enlace de invitación.
"""
from __future__ import annotations

import httpx

from app.config import get_settings
from app.errors import DomainError
from app.seguridad.oidc import ROL_LLAVE_FISICA, _descubrimiento, interna

INVITACION_SEGUNDOS = 24 * 3600  # ciclo-vida §4: la invitación caduca en 24 horas


def _base() -> str:
    issuer = get_settings().oidc_issuer
    raiz, realm = issuer.split("/realms/", 1)
    return interna(f"{raiz}/admin/realms/{realm}")


def _token() -> str:
    s = get_settings()
    if not s.idp_admin_client_secret:
        raise DomainError("Falta FACTURAS_IDP_ADMIN_CLIENT_SECRET para administrar usuarios.", 503)
    r = httpx.post(
        interna(_descubrimiento(s.oidc_issuer)["token_endpoint"]),
        data={"grant_type": "client_credentials", "client_id": s.idp_admin_client_id, "client_secret": s.idp_admin_client_secret},
        timeout=30,
    )
    if r.status_code != 200:
        raise DomainError("El proveedor de identidad rechazó la cuenta de administración.", 503)
    return r.json()["access_token"]


def _req(metodo: str, ruta: str, **kw) -> httpx.Response:
    r = httpx.request(metodo, f"{_base()}{ruta}", headers={"Authorization": f"Bearer {_token()}"}, timeout=60, **kw)
    if r.status_code >= 400:
        raise DomainError(f"Keycloak respondió {r.status_code} al administrar usuarios.", 502)
    return r


def buscar_usuario(correo: str) -> str | None:
    usuarios = _req("GET", "/users", params={"email": correo, "exact": "true"}).json()
    return usuarios[0]["id"] if usuarios else None


def crear_usuario(correo: str, nombre: str, *, llave_fisica: bool) -> str:
    if buscar_usuario(correo):
        raise DomainError("Ya existe una cuenta con ese correo en el proveedor de identidad.", 409)
    partes = nombre.split(" ", 1)
    r = _req(
        "POST",
        "/users",
        json={
            "username": correo, "email": correo, "emailVerified": True, "enabled": True,
            "firstName": partes[0], "lastName": partes[1] if len(partes) > 1 else "",
        },
    )
    user_id = r.headers["Location"].rsplit("/", 1)[1]
    if llave_fisica:
        rol = _req("GET", f"/roles/{ROL_LLAVE_FISICA}").json()
        _req("POST", f"/users/{user_id}/role-mappings/realm", json=[rol])
    return user_id


def fijar_llave_fisica(user_id: str, requerida: bool) -> None:
    rol = _req("GET", f"/roles/{ROL_LLAVE_FISICA}").json()
    _req("POST" if requerida else "DELETE", f"/users/{user_id}/role-mappings/realm", json=[rol])


def enviar_invitacion(user_id: str, *, llave_fisica: bool) -> None:
    """Enlace de un solo uso por correo para registrar el autenticador (y códigos si no es privilegiado)."""
    s = get_settings()
    acciones = ["webauthn-register"] if llave_fisica else ["webauthn-register-passwordless", "CONFIGURE_RECOVERY_AUTHN_CODES"]
    _req(
        "PUT",
        f"/users/{user_id}/execute-actions-email",
        params={"client_id": s.oidc_client_id, "redirect_uri": f"{s.app_url}/auth/callback", "lifespan": INVITACION_SEGUNDOS},
        json=acciones,
    )


def deshabilitar(user_id: str) -> None:
    _req("PUT", f"/users/{user_id}", json={"enabled": False})
    cerrar_sesiones(user_id)


def cerrar_sesiones(user_id: str) -> None:
    _req("POST", f"/users/{user_id}/logout")


TIPOS_FUERTES = {"webauthn": "Llave física", "webauthn-passwordless": "Passkey", "recovery-authn-codes": "Códigos de recuperación"}


def autenticadores(user_id: str) -> list[dict]:
    """Metadatos de los autenticadores registrados (sin material criptográfico)."""
    return [
        {"id": c["id"], "tipo": c["type"], "tipo_nombre": TIPOS_FUERTES.get(c["type"], c["type"]),
         "etiqueta": c.get("userLabel"), "creado": c.get("createdDate")}
        for c in _req("GET", f"/users/{user_id}/credentials").json()
    ]


def eliminar_autenticador(user_id: str, credencial_id: str) -> None:
    _req("DELETE", f"/users/{user_id}/credentials/{credencial_id}")


def eliminar_todos_los_autenticadores(user_id: str) -> int:
    lista = autenticadores(user_id)
    for c in lista:
        eliminar_autenticador(user_id, c["id"])
    return len(lista)


def habilitar(user_id: str) -> None:
    _req("PUT", f"/users/{user_id}", json={"enabled": True})
