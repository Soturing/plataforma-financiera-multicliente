"""Sesiones de la aplicación (ciclo-vida-usuarios §7, D-020).

El navegador guarda sólo un token aleatorio en una cookie HttpOnly; la base
guarda su huella SHA-256. Cada petición vuelve a comprobar identidad, asignación
y vigencia: una autorización retirada deja de valer en la siguiente petición.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

from psycopg import Connection

from app.config import get_settings
from app.seguridad import control
from app.seguridad.politica import ROLES_PRIVILEGIADOS, Nivel, modulos_visibles

# Una cookie por cliente: en producción cada cliente tiene su subdominio; en local,
# varios clientes en puertos distintos de 127.0.0.1 compartirían la misma cookie.
COOKIE = "fa_sesion_" + get_settings().tenant_clave.lower()

INACTIVIDAD_PRIVILEGIADA = timedelta(minutes=15)
ABSOLUTA_PRIVILEGIADA = timedelta(hours=8)
INACTIVIDAD_OPERATIVA = timedelta(minutes=30)
ABSOLUTA_OPERATIVA = timedelta(hours=12)
MAX_SESIONES = {True: 2, False: 3}  # privilegiado → máximo de dispositivos activos

# Antigüedad máxima de la última autenticación para cada nivel (acciones-sensibles §2).
RECIENTE = {Nivel.C2: timedelta(minutes=15), Nivel.C3: timedelta(minutes=5)}
_TOQUE_MINIMO = timedelta(seconds=30)


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def huella(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


@dataclass
class Contexto:
    sesion_id: UUID
    identidad_id: UUID
    nombre: str
    correo: str
    llave_fisica: bool
    autenticado_en: datetime
    expira_absoluta: datetime
    expira_inactividad: datetime
    metodo_auth: str
    asignacion_id: UUID | None = None
    rol: str | None = None
    rol_nombre: str | None = None
    tenant_id: UUID | None = None
    tenant_clave: str | None = None
    modulos: list[str] | None = None
    sucursales: list[str] | None = None
    restaurantes: list[str] = field(default_factory=list)
    condicionados: list[str] = field(default_factory=list)
    opciones: list[dict] = field(default_factory=list)

    @property
    def etiqueta(self) -> str:
        """Texto que se guarda en los campos de autor de la base de negocio."""
        return f"{self.nombre} <{self.correo}>"

    @property
    def privilegiado(self) -> bool:
        return self.rol in ROLES_PRIVILEGIADOS

    def reciente(self, nivel: Nivel) -> bool:
        limite = RECIENTE.get(nivel)
        return limite is None or ahora() - self.autenticado_en <= limite

    def publico(self) -> dict:
        return {
            "autenticado": True,
            "nombre": self.nombre,
            "correo": self.correo,
            "rol": self.rol,
            "rol_nombre": self.rol_nombre,
            "tenant": self.tenant_clave,
            "modulos": modulos_visibles(self.rol, self.modulos) if self.rol else [],
            "sucursales": self.sucursales,
            "restaurantes": self.restaurantes,
            "condicionados": self.condicionados,
            "llave_fisica": self.llave_fisica,
            "metodo_auth": self.metodo_auth,
            "autenticado_en": self.autenticado_en.isoformat(),
            "expira_absoluta": self.expira_absoluta.isoformat(),
            "expira_inactividad": self.expira_inactividad.isoformat(),
            "requiere_contexto": self.asignacion_id is None,
            "opciones": [
                {
                    "asignacion_id": str(o["id"]), "rol": o["rol"], "rol_nombre": o["rol_nombre"],
                    "tenant": o["tenant_clave"] or "Todos los clientes", "sucursales": o["sucursales"],
                    "restaurantes": o["restaurantes"],
                    "disponible": o.get("disponible", True), "motivo": o.get("motivo_no_disponible"),
                }
                for o in self.opciones
            ],
        }


def _tiempos(privilegiado: bool) -> tuple[timedelta, timedelta]:
    if privilegiado:
        return INACTIVIDAD_PRIVILEGIADA, ABSOLUTA_PRIVILEGIADA
    return INACTIVIDAD_OPERATIVA, ABSOLUTA_OPERATIVA


def opciones_disponibles(asignaciones: list[dict], *, llave_fisica: bool, tenant_id: UUID) -> list[dict]:
    """Asignaciones que pueden usarse en este data plane con la autenticación actual."""
    resultado = []
    for a in asignaciones:
        a = dict(a)
        a["disponible"], a["motivo_no_disponible"] = True, None
        if a["tenant_id"] is not None and a["tenant_id"] != tenant_id:
            continue  # pertenece a otro cliente: no se muestra en este data plane
        if a["tenant_id"] is not None and a["tenant_estado"] != "ACTIVO":
            a["disponible"], a["motivo_no_disponible"] = False, "El servicio del cliente no está activo."
        if a["privilegiado"] and not llave_fisica:
            a["disponible"], a["motivo_no_disponible"] = False, "Este rol exige iniciar sesión con llave física."
        resultado.append(a)
    return resultado


def crear_sesion(
    conn: Connection,
    *,
    tenant_id: UUID,
    identidad: dict,
    asignaciones: list[dict],
    llave_fisica: bool,
    autenticado_en: datetime,
    idp_sid: str | None,
    ip: str | None,
    agente: str | None,
) -> tuple[str, UUID]:
    """Crea la sesión (sin cliente ni rol todavía). Devuelve el token para la cookie."""
    privilegiada = any(a["privilegiado"] for a in asignaciones)
    inactividad, absoluta = _tiempos(privilegiada)
    token = secrets.token_urlsafe(48)
    fila = conn.execute(
        """
        INSERT INTO control.sesiones (token_hash, identidad_id, tenant_id, inactividad_max, expira_absoluta,
                                      autenticado_en, metodo_auth, llave_fisica, idp_sid, ip, agente)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (
            huella(token), identidad["id"], tenant_id, inactividad, ahora() + absoluta, autenticado_en,
            "LLAVE_FISICA" if llave_fisica else "PASSKEY", llave_fisica, idp_sid, ip, (agente or "")[:300],
        ),
    ).fetchone()
    _limitar_dispositivos(conn, identidad["id"], privilegiada, conservar=fila["id"])
    conn.execute("UPDATE control.identidades SET ultimo_acceso_en = now() WHERE id = %s", (identidad["id"],))
    return token, fila["id"]


def _limitar_dispositivos(conn: Connection, identidad_id: UUID, privilegiada: bool, conservar: UUID) -> None:
    """Cierra las sesiones más antiguas por encima del máximo recomendado de dispositivos."""
    conn.execute(
        """
        UPDATE control.sesiones SET revocada_en = now(), motivo_revocacion = 'Límite de dispositivos activos'
        WHERE id IN (
            SELECT id FROM control.sesiones
            WHERE identidad_id = %s AND revocada_en IS NULL AND expira_absoluta > now() AND id <> %s
            ORDER BY creada_en DESC OFFSET %s
        )
        """,
        (identidad_id, conservar, MAX_SESIONES[privilegiada] - 1),
    )


def fijar_contexto(conn: Connection, sesion_id: UUID, asignacion: dict, tenant_id: UUID) -> None:
    inactividad, absoluta = _tiempos(asignacion["privilegiado"])
    conn.execute(
        """
        UPDATE control.sesiones
        SET asignacion_id = %s, rol_activo = %s, tenant_id = %s, inactividad_max = %s,
            expira_absoluta = least(expira_absoluta, creada_en + %s), ultimo_uso = now()
        WHERE id = %s
        """,
        (asignacion["id"], asignacion["rol"], tenant_id, inactividad, absoluta, sesion_id),
    )


def registrar_reautenticacion(conn: Connection, sesion_id: UUID, autenticado_en: datetime, llave_fisica: bool) -> None:
    conn.execute(
        "UPDATE control.sesiones SET autenticado_en = %s, llave_fisica = llave_fisica OR %s, ultimo_uso = now() WHERE id = %s",
        (autenticado_en, llave_fisica, sesion_id),
    )


def revocar(conn: Connection, sesion_id: UUID, motivo: str) -> None:
    conn.execute(
        "UPDATE control.sesiones SET revocada_en = now(), motivo_revocacion = %s WHERE id = %s AND revocada_en IS NULL",
        (motivo, sesion_id),
    )


def revocar_todas(conn: Connection, identidad_id: UUID, motivo: str) -> int:
    return conn.execute(
        "UPDATE control.sesiones SET revocada_en = now(), motivo_revocacion = %s WHERE identidad_id = %s AND revocada_en IS NULL",
        (motivo, identidad_id),
    ).rowcount


def resolver(conn: Connection, token: str | None, tenant: dict) -> tuple[Contexto | None, str | None]:
    """Devuelve el contexto vigente o el motivo por el que la sesión ya no vale."""
    tenant_id = tenant["id"]
    if not token or len(token) > 200:
        return None, None
    s = conn.execute("SELECT * FROM control.sesiones WHERE token_hash = %s", (huella(token),)).fetchone()
    if s is None:
        return None, "desconocida"
    if s["revocada_en"] is not None:
        return None, "revocada"
    if s["tenant_id"] is not None and s["tenant_id"] != tenant_id:
        # Sesión de otro cliente: se rechaza aquí sin cerrarla en su cliente legítimo.
        return None, "otro_tenant"
    momento = ahora()
    if s["expira_absoluta"] <= momento:
        revocar(conn, s["id"], "Duración máxima alcanzada")
        return None, "expirada"
    if s["ultimo_uso"] + s["inactividad_max"] <= momento:
        revocar(conn, s["id"], "Inactividad")
        return None, "inactiva"

    ident = control.identidad(conn, s["identidad_id"])
    if ident is None or ident["estado"] != "ACTIVA":
        revocar(conn, s["id"], "Identidad no activa")
        return None, "identidad_no_activa"

    asignaciones = control.asignaciones_vigentes(conn, s["identidad_id"])
    opciones = opciones_disponibles(asignaciones, llave_fisica=s["llave_fisica"], tenant_id=tenant_id)
    ctx = Contexto(
        sesion_id=s["id"], identidad_id=ident["id"], nombre=ident["nombre"], correo=ident["correo"],
        llave_fisica=s["llave_fisica"], autenticado_en=s["autenticado_en"], expira_absoluta=s["expira_absoluta"],
        expira_inactividad=momento + s["inactividad_max"], metodo_auth=s["metodo_auth"], opciones=opciones,
    )
    if s["asignacion_id"] is not None:
        actual = next((a for a in opciones if a["id"] == s["asignacion_id"] and a["disponible"]), None)
        if actual is None:
            # Se retiró o cambió la asignación: la sesión no conserva la autorización (§8.1).
            revocar(conn, s["id"], "Asignación retirada")
            return None, "asignacion_retirada"
        ctx.asignacion_id, ctx.rol, ctx.rol_nombre = actual["id"], actual["rol"], actual["rol_nombre"]
        ctx.tenant_id, ctx.tenant_clave = tenant_id, tenant["clave"]
        ctx.modulos, ctx.sucursales, ctx.condicionados = actual["modulos"], actual["sucursales"], actual["condicionados"] or []
        ctx.restaurantes = actual["restaurantes"] or []

    if momento - s["ultimo_uso"] >= _TOQUE_MINIMO:
        conn.execute("UPDATE control.sesiones SET ultimo_uso = %s WHERE id = %s", (momento, s["id"]))
    return ctx, None
