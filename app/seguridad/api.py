"""Rutas de acceso (fase 3) y de administración de identidades y auditoría.

- `/auth/*`: inicio y cierre de sesión con el proveedor de identidad.
- `/api/v1/seguridad/sesion` y `/contexto`: sesión actual y elección de cliente y rol.
- `/api/v1/seguridad/identidades`, `/invitaciones`, `/auditoria`: administración,
  protegidas por `autorizar_ruta` como cualquier otra ruta de datos.
"""
from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.errors import DomainError
from app.seguridad import control, keycloak_admin, notificaciones, oidc, sesiones
from app.seguridad.politica import ROLES_GLOBALES, ROLES_PRIVILEGIADOS

router = APIRouter()

_SOLICITUD_VIGENCIA = timedelta(minutes=10)


def _destino_seguro(destino: str | None) -> str:
    """Sólo rutas internas: evita redirecciones abiertas hacia otros sitios."""
    if not destino or not destino.startswith("/") or destino.startswith("//") or "\\" in destino:
        return "/#/"
    return destino


def _ip(request: Request) -> str | None:
    return control.ip_cliente(request)


def _tenant(conn) -> dict:
    tenant = control.tenant_por_clave(conn, get_settings().tenant_clave)
    if tenant is None:
        raise DomainError("Falta registrar este cliente en el plano de control (python -m app.seguridad.instalar cliente).", 503)
    return tenant


def _contexto(request: Request, conn) -> sesiones.Contexto:
    ctx, _ = sesiones.resolver(conn, request.cookies.get(sesiones.COOKIE), _tenant(conn))
    if ctx is None:
        raise DomainError("Inicie sesión para continuar.", 401)
    return ctx


def _poner_cookie(respuesta, token: str) -> None:
    respuesta.set_cookie(
        sesiones.COOKIE, token, httponly=True, secure=get_settings().cookie_segura, samesite="lax",
        path="/", max_age=int(sesiones.ABSOLUTA_OPERATIVA.total_seconds()),
    )


# --------------------------------------------------------------------------- #
# Inicio y cierre de sesión


def _iniciar(proposito: str, destino: str, *, sesion_id: UUID | None = None, asignacion: UUID | None = None,
             correo: str | None = None, accion_kc: str | None = None) -> RedirectResponse:
    verifier, challenge = oidc.nuevo_pkce()
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with control.conexion_control() as conn:
        conn.execute("DELETE FROM control.solicitudes_acceso WHERE creada_en < now() - interval '1 day'")
        conn.execute(
            """INSERT INTO control.solicitudes_acceso (state, verifier, nonce, destino, proposito, sesion_id, asignacion_destino)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (state, verifier, nonce, _destino_seguro(destino), proposito, sesion_id, asignacion),
        )
    url = oidc.url_autorizacion(state=state, nonce=nonce, challenge=challenge, reautenticar=proposito == "REAUTENTICAR",
                                correo=correo, accion_kc=accion_kc)
    return RedirectResponse(url, status_code=303)


@router.get("/auth/entrar", include_in_schema=False)
def entrar(destino: str = "/#/"):
    return _iniciar("ENTRAR", destino)


@router.get("/auth/reautenticar", include_in_schema=False)
def reautenticar(request: Request, destino: str = "/#/", asignacion: UUID | None = None):
    with control.conexion_control() as conn:
        ctx = _contexto(request, conn)
    return _iniciar("REAUTENTICAR", destino, sesion_id=ctx.sesion_id, asignacion=asignacion, correo=ctx.correo)


@router.get("/auth/registrar-autenticador", include_in_schema=False)
def registrar_autenticador(request: Request, destino: str = "/#/accesos"):
    """Agrega un autenticador desde la sesión (segunda passkey, llave de respaldo o reemplazo tras recuperación)."""
    with control.conexion_control() as conn:
        ctx = _contexto(request, conn)
    privilegiada = any(o["privilegiado"] for o in ctx.opciones)
    accion = "webauthn-register" if privilegiada else "webauthn-register-passwordless"
    return _iniciar("REGISTRAR_AUTENTICADOR", destino, sesion_id=ctx.sesion_id, correo=ctx.correo, accion_kc=accion)


@router.get("/auth/callback", include_in_schema=False)
def callback(request: Request, state: str | None = None, code: str | None = None, error: str | None = None,
             kc_action_status: str | None = None):
    if not state:
        # Regreso desde el enlace de invitación: el autenticador quedó registrado.
        return RedirectResponse("/#/?acceso=registrado", status_code=303)
    with control.conexion_control() as conn:
        solicitud = conn.execute(
            "UPDATE control.solicitudes_acceso SET usada_en = now() WHERE state = %s AND usada_en IS NULL "
            "AND creada_en > now() - %s RETURNING *",
            (state, _SOLICITUD_VIGENCIA),
        ).fetchone()
    if solicitud is None or error or not code:
        return RedirectResponse("/#/?acceso=cancelado", status_code=303)

    verificada = oidc.canjear_codigo(code, solicitud["verifier"], solicitud["nonce"])
    metodo = verificada.metodo
    ip, agente = _ip(request), request.headers.get("user-agent")
    with control.conexion_control() as conn:
        tenant = _tenant(conn)
        ident = control.identidad_por_subject(conn, verificada.subject)
        if ident is None or ident["estado"] not in ("ACTIVA", "REGISTRO_PENDIENTE", "INVITADA"):
            control.registrar_evento(
                conn, "INICIO_SESION", "RECHAZO", actor_id=ident["id"] if ident else None,
                actor_tipo="PERSONA" if ident else "ANONIMO", tenant_id=tenant["id"], ip=ip, metodo_auth=metodo,
                politica="IDENTIDAD_NO_ACTIVA" if ident else "SIN_IDENTIDAD",
                detalle={"estado": ident["estado"] if ident else None},
            )
            return RedirectResponse("/#/?acceso=sin_acceso", status_code=303)
        if ident["estado"] != "ACTIVA":
            conn.execute(
                "UPDATE control.identidades SET estado = 'ACTIVA', requiere_nuevo_autenticador = false, actualizado_en = now() "
                "WHERE id = %s",
                (ident["id"],),
            )
            control.registrar_evento(conn, "ACTIVACION", actor_id=ident["id"], tenant_id=tenant["id"], ip=ip, metodo_auth=metodo)
            notificaciones.a_persona(conn, ident, "ACTIVACION")
            notificaciones.a_directores(conn, "ACTIVACION_DIRECTOR", excepto=ident["id"], nombre=ident["nombre"])
            ident = control.identidad(conn, ident["id"])
        if metodo == "CODIGO_RECUPERACION":
            # Recuperación normal (§10.1): entra, pero debe registrar una passkey nueva antes de operar.
            conn.execute("UPDATE control.identidades SET requiere_nuevo_autenticador = true WHERE id = %s", (ident["id"],))
            control.registrar_evento(conn, "USO_CODIGO_RECUPERACION", actor_id=ident["id"], tenant_id=tenant["id"], ip=ip,
                                     metodo_auth=metodo, sensibilidad="ALERTA")
            notificaciones.a_persona(conn, ident, "CODIGO_RECUPERACION")

        if solicitud["proposito"] in ("REAUTENTICAR", "REGISTRAR_AUTENTICADOR"):
            ctx, _ = sesiones.resolver(conn, request.cookies.get(sesiones.COOKIE), tenant)
            if ctx is None or ctx.sesion_id != solicitud["sesion_id"] or ctx.identidad_id != ident["id"]:
                control.registrar_evento(conn, solicitud["proposito"], "RECHAZO", actor_id=ident["id"], tenant_id=tenant["id"],
                                         ip=ip, metodo_auth=metodo, politica="SESION_DISTINTA")
                return RedirectResponse("/#/?acceso=sesion_distinta", status_code=303)
            if solicitud["proposito"] == "REGISTRAR_AUTENTICADOR":
                exito = kc_action_status == "success"
                control.registrar_evento(conn, "AUTENTICADOR_REGISTRADO", "EXITO" if exito else "RECHAZO",
                                         actor_id=ident["id"], rol=ctx.rol, tenant_id=tenant["id"], sesion_id=ctx.sesion_id,
                                         ip=ip, metodo_auth=metodo, sensibilidad="C2", detalle={"estado": kc_action_status})
                if exito:
                    conn.execute("UPDATE control.identidades SET requiere_nuevo_autenticador = false WHERE id = %s", (ident["id"],))
                    notificaciones.a_persona(conn, ident, "AUTENTICADOR_REGISTRADO")
                destino = solicitud["destino"] + ("" if exito else "?acceso=registro_cancelado")
                return RedirectResponse(destino, status_code=303)
            sesiones.registrar_reautenticacion(conn, ctx.sesion_id, verificada.autenticado_en, verificada.llave_fisica)
            control.registrar_evento(conn, "REAUTENTICACION", actor_id=ident["id"], rol=ctx.rol, tenant_id=tenant["id"],
                                     sesion_id=ctx.sesion_id, ip=ip, metodo_auth=metodo)
            if solicitud["asignacion_destino"]:
                _cambiar_contexto(conn, ctx.sesion_id, ident["id"], solicitud["asignacion_destino"], tenant,
                                  llave_fisica=ctx.llave_fisica or verificada.llave_fisica, ip=ip, rol_anterior=ctx.rol)
            return RedirectResponse(solicitud["destino"], status_code=303)

        asignaciones = control.asignaciones_vigentes(conn, ident["id"])
        opciones = sesiones.opciones_disponibles(asignaciones, llave_fisica=verificada.llave_fisica, tenant_id=tenant["id"])
        if not opciones:
            control.registrar_evento(conn, "INICIO_SESION", "RECHAZO", actor_id=ident["id"], tenant_id=tenant["id"],
                                     ip=ip, metodo_auth=metodo, politica="SIN_ASIGNACION_EN_ESTE_CLIENTE")
            return RedirectResponse("/#/?acceso=sin_asignacion", status_code=303)
        token, sesion_id = sesiones.crear_sesion(
            conn, tenant_id=tenant["id"], identidad=ident, asignaciones=asignaciones, llave_fisica=verificada.llave_fisica,
            metodo=metodo, autenticado_en=verificada.autenticado_en, idp_sid=verificada.idp_sid, ip=ip, agente=agente,
        )
        control.registrar_evento(conn, "INICIO_SESION", actor_id=ident["id"], tenant_id=tenant["id"], sesion_id=sesion_id,
                                 ip=ip, metodo_auth=metodo, detalle={"agente": (agente or "")[:120]})
        disponibles = [o for o in opciones if o["disponible"]]
        if len(disponibles) == 1:
            _cambiar_contexto(conn, sesion_id, ident["id"], disponibles[0]["id"], tenant,
                              llave_fisica=verificada.llave_fisica, ip=ip, rol_anterior=None)
    destino = solicitud["destino"]
    if metodo == "CODIGO_RECUPERACION":
        destino = "/auth/registrar-autenticador?destino=" + quote(destino, safe="")
    respuesta = RedirectResponse(destino, status_code=303)
    _poner_cookie(respuesta, token)
    return respuesta


@router.post("/auth/salir", include_in_schema=False)
def salir(request: Request):
    with control.conexion_control() as conn:
        tenant = _tenant(conn)
        ctx, _ = sesiones.resolver(conn, request.cookies.get(sesiones.COOKIE), tenant)
        if ctx is not None:
            sesiones.revocar(conn, ctx.sesion_id, "Cierre de sesión")
            control.registrar_evento(conn, "CIERRE_SESION", actor_id=ctx.identidad_id, rol=ctx.rol,
                                     tenant_id=tenant["id"], sesion_id=ctx.sesion_id, ip=_ip(request))
    try:
        destino = oidc.url_cierre_proveedor()
    except Exception:  # el proveedor puede no estar disponible; la sesión local ya se cerró
        destino = "/#/"
    respuesta = JSONResponse({"redirect": destino})
    respuesta.delete_cookie(sesiones.COOKIE, path="/")
    return respuesta


@router.get("/auth/salida", include_in_schema=False)
def salida():
    return RedirectResponse("/#/?acceso=cerrado", status_code=303)


# --------------------------------------------------------------------------- #
# Sesión actual y contexto


@router.get("/api/v1/seguridad/sesion", tags=["seguridad"])
def sesion_actual(request: Request):
    s = get_settings()
    base = {"modo": s.acceso_modo, "control": control.control_configurado()}
    if not control.control_configurado():
        return {**base, "autenticado": False}
    with control.conexion_control() as conn:
        tenant = control.tenant_por_clave(conn, s.tenant_clave)
        if tenant is None:
            return {**base, "autenticado": False, "instalacion_pendiente": True}
        ctx, motivo = sesiones.resolver(conn, request.cookies.get(sesiones.COOKIE), tenant)
    if ctx is None:
        return {**base, "autenticado": False, "motivo": motivo}
    return {**base, **ctx.publico()}


class ContextoRequest(BaseModel):
    asignacion_id: UUID


def _cambiar_contexto(conn, sesion_id, identidad_id, asignacion_id, tenant, *, llave_fisica: bool, ip, rol_anterior) -> dict:
    opciones = sesiones.opciones_disponibles(control.asignaciones_vigentes(conn, identidad_id), llave_fisica=llave_fisica, tenant_id=tenant["id"])
    elegida = next((o for o in opciones if o["id"] == asignacion_id), None)
    if elegida is None or not elegida["disponible"]:
        motivo = elegida["motivo_no_disponible"] if elegida else "La asignación no existe o no está vigente."
        control.registrar_evento(conn, "CAMBIO_CONTEXTO", "RECHAZO", actor_id=identidad_id, tenant_id=tenant["id"],
                                 sesion_id=sesion_id, ip=ip, motivo=motivo)
        raise DomainError(motivo, 403)
    sesiones.fijar_contexto(conn, sesion_id, elegida, tenant["id"])
    control.registrar_evento(conn, "CAMBIO_CONTEXTO", actor_id=identidad_id, rol=elegida["rol"], tenant_id=tenant["id"],
                             sesion_id=sesion_id, ip=ip, detalle={"rol_anterior": rol_anterior, "asignacion": str(elegida["id"])})
    return elegida


@router.post("/api/v1/seguridad/contexto", tags=["seguridad"])
def elegir_contexto(datos: ContextoRequest, request: Request):
    """Elige cliente y rol. Cambiar de un rol a otro exige reautenticación (D-020)."""
    with control.conexion_control() as conn:
        tenant = _tenant(conn)
        ctx = _contexto(request, conn)
        if ctx.asignacion_id is not None and ctx.asignacion_id != datos.asignacion_id and not ctx.reciente(sesiones.Nivel.C3):
            return JSONResponse(
                status_code=401,
                content={"detail": {"codigo": "REAUTENTICACION_REQUERIDA", "mensaje": "Confirme su identidad para cambiar de rol.",
                                    "url": f"/auth/reautenticar?asignacion={datos.asignacion_id}&destino=/%23/"}},
            )
        _cambiar_contexto(conn, ctx.sesion_id, ctx.identidad_id, datos.asignacion_id, tenant,
                          llave_fisica=ctx.llave_fisica, ip=_ip(request), rol_anterior=ctx.rol)
        nuevo, _ = sesiones.resolver(conn, request.cookies.get(sesiones.COOKIE), tenant)
    return nuevo.publico()


# --------------------------------------------------------------------------- #
# Administración de identidades (protegida por autorizar_ruta: IDENTIDADES)


@router.get("/api/v1/seguridad/identidades", tags=["seguridad"])
def identidades(request: Request):
    with control.conexion_control() as conn:
        tenant = _tenant(conn)
        return {
            "identidades": control.listar_identidades(conn),
            "restaurantes": control.restaurantes_tenant(conn, tenant["id"]),
            "sucursales": control.sucursales_tenant(conn, tenant["id"]),
        }


class InvitacionRequest(BaseModel):
    correo: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)
    nombre: str = Field(min_length=3, max_length=120)
    rol: Literal[
        "CONSULTORA_DIRECTOR", "CONSULTORA_SEGURIDAD", "CONSULTORA_CAPTURISTA", "SOPORTE_TECNICO",
        "CLIENTE_RESPONSABLE", "CLIENTE_FINANZAS", "CLIENTE_OPERADOR",
    ]
    modulos: list[str] | None = None
    # Alcance: restaurantes completos y/o sucursales sueltas. Ambos vacíos = todas.
    restaurantes: list[str] | None = None
    sucursales: list[str] | None = None
    condicionados: list[str] = Field(default_factory=list)
    vigente_hasta: str | None = None
    motivo: str = Field(min_length=5, max_length=300)


@router.post("/api/v1/seguridad/invitaciones", status_code=201, tags=["seguridad"])
def invitar(datos: InvitacionRequest, request: Request):
    """Registra a la persona, su asignación y envía la invitación de un solo uso (ciclo-vida §4)."""
    ctx: sesiones.Contexto = request.state.contexto
    if datos.rol in ROLES_GLOBALES and ctx.rol != "CONSULTORA_DIRECTOR":
        raise DomainError("Sólo el director puede otorgar un rol global.", 403)
    if datos.rol == "SOPORTE_TECNICO" and (datos.modulos or datos.sucursales or datos.restaurantes):
        raise DomainError("Soporte técnico no recibe acceso a contenido de clientes.", 422)
    llave = datos.rol in ROLES_PRIVILEGIADOS
    with control.conexion_control() as conn:
        tenant = _tenant(conn)
        if conn.execute("SELECT 1 FROM control.identidades WHERE lower(correo) = lower(%s)", (datos.correo,)).fetchone():
            raise DomainError("Ya existe una persona con ese correo. Agregue la asignación desde su ficha.", 409)
        if datos.correo.lower() == ctx.correo.lower():
            raise DomainError("No puede invitarse ni ampliar su propio acceso.", 403)
        validos_r = {r["clave"] for r in control.restaurantes_tenant(conn, tenant["id"])}
        validos_s = {s["clave"] for s in control.sucursales_tenant(conn, tenant["id"])}
        if set(datos.restaurantes or []) - validos_r or set(datos.sucursales or []) - validos_s:
            raise DomainError("Restaurante o sucursal fuera de este cliente.", 422)
        user_id = keycloak_admin.crear_usuario(datos.correo, datos.nombre, llave_fisica=llave)
        ident = conn.execute(
            "INSERT INTO control.identidades (idp_subject, correo, nombre, estado) VALUES (%s, %s, %s, 'INVITADA') RETURNING *",
            (user_id, datos.correo, datos.nombre),
        ).fetchone()
        asignacion = conn.execute(
            """INSERT INTO control.asignaciones (identidad_id, rol, tenant_id, modulos, condicionados,
                                                 vigente_hasta, motivo, creado_por)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (ident["id"], datos.rol, None if datos.rol in ROLES_GLOBALES else tenant["id"], datos.modulos,
             datos.condicionados, datos.vigente_hasta, datos.motivo, ctx.identidad_id),
        ).fetchone()
        if datos.rol not in ROLES_GLOBALES:
            control.guardar_alcance(conn, asignacion["id"], tenant["id"], datos.restaurantes, datos.sucursales)
        keycloak_admin.enviar_invitacion(user_id, llave_fisica=llave)
        control.registrar_evento(
            conn, "INVITACION", actor_id=ctx.identidad_id, rol=ctx.rol, tenant_id=tenant["id"], modulo="IDENTIDADES",
            accion="ADMINISTRAR", recurso_tipo="identidad", recurso_id=str(ident["id"]), sesion_id=ctx.sesion_id,
            ip=_ip(request), motivo=datos.motivo, sensibilidad="C3" if datos.rol in ROLES_GLOBALES else "C2",
            detalle={"rol": datos.rol, "modulos": datos.modulos, "restaurantes": datos.restaurantes, "sucursales": datos.sucursales,
                     "condicionados": datos.condicionados, "asignacion": str(asignacion["id"])},
        )
    return {"identidad_id": str(ident["id"]), "estado": "INVITADA", "llave_fisica": llave}


class SuspensionRequest(BaseModel):
    motivo: str = Field(min_length=5, max_length=300)


@router.post("/api/v1/seguridad/identidades/{identidad_id}/suspender", tags=["seguridad"])
def suspender(identidad_id: UUID, datos: SuspensionRequest, request: Request):
    """Suspensión administrativa: revoca sesiones y bloquea en el proveedor (ciclo-vida §11.2)."""
    ctx: sesiones.Contexto = request.state.contexto
    if identidad_id == ctx.identidad_id:
        raise DomainError("No puede suspender su propia cuenta.", 403)
    with control.conexion_control() as conn:
        ident = control.identidad(conn, identidad_id)
        if ident is None:
            raise DomainError("Persona no encontrada.", 404)
        conn.execute(
            "UPDATE control.identidades SET estado = 'SUSPENDIDA', motivo_estado = %s, actualizado_en = now() WHERE id = %s",
            (datos.motivo, identidad_id),
        )
        cerradas = sesiones.revocar_todas(conn, identidad_id, "Suspensión administrativa")
        if ident["idp_subject"]:
            keycloak_admin.deshabilitar(ident["idp_subject"])
        control.registrar_evento(
            conn, "SUSPENSION", actor_id=ctx.identidad_id, rol=ctx.rol, tenant_id=ctx.tenant_id, modulo="IDENTIDADES",
            accion="ADMINISTRAR", recurso_tipo="identidad", recurso_id=str(identidad_id), sesion_id=ctx.sesion_id,
            ip=_ip(request), motivo=datos.motivo, sensibilidad="C2", detalle={"sesiones_revocadas": cerradas},
        )
    return {"estado": "SUSPENDIDA", "sesiones_revocadas": cerradas}


@router.post("/api/v1/seguridad/identidades/{identidad_id}/revocar-sesiones", tags=["seguridad"])
def revocar_sesiones(identidad_id: UUID, datos: SuspensionRequest, request: Request):
    ctx: sesiones.Contexto = request.state.contexto
    with control.conexion_control() as conn:
        cerradas = sesiones.revocar_todas(conn, identidad_id, datos.motivo)
        ident = control.identidad(conn, identidad_id)
        if ident and ident["idp_subject"]:
            keycloak_admin.cerrar_sesiones(ident["idp_subject"])
        control.registrar_evento(
            conn, "REVOCACION_SESIONES", actor_id=ctx.identidad_id, rol=ctx.rol, tenant_id=ctx.tenant_id,
            modulo="IDENTIDADES", accion="ADMINISTRAR", recurso_tipo="identidad", recurso_id=str(identidad_id),
            sesion_id=ctx.sesion_id, ip=_ip(request), motivo=datos.motivo, sensibilidad="C2",
            detalle={"sesiones_revocadas": cerradas},
        )
    return {"sesiones_revocadas": cerradas}


# --------------------------------------------------------------------------- #
# Auditoría (protegida por autorizar_ruta: AUDITORIA)


@router.get("/api/v1/seguridad/auditoria", tags=["seguridad"])
def auditoria(request: Request, limite: int = Query(default=100, ge=1, le=500)):
    """Alcance según auditoria-alertas §9: global para roles de consultora, propio cliente para el responsable."""
    ctx: sesiones.Contexto = request.state.contexto
    with control.conexion_control() as conn:
        if ctx.rol in ("CONSULTORA_DIRECTOR", "CONSULTORA_SEGURIDAD"):
            eventos = control.listar_auditoria(conn, tenant_id=None, actor_id=None, limite=limite)
        elif ctx.rol == "CLIENTE_RESPONSABLE":
            eventos = control.listar_auditoria(conn, tenant_id=ctx.tenant_id, actor_id=None, limite=limite)
        else:
            eventos = control.listar_auditoria(conn, tenant_id=None, actor_id=ctx.identidad_id, limite=limite)
        integridad = control.verificar_auditoria(conn)
    return {"eventos": eventos, "integridad": integridad}


@router.get("/api/v1/seguridad/mi-actividad", tags=["seguridad"])
def mi_actividad(request: Request, limite: int = Query(default=50, ge=1, le=200)):
    """Actividad propia: disponible para cualquier persona con sesión (matriz §9)."""
    with control.conexion_control() as conn:
        ctx = _contexto(request, conn)
        return {"eventos": control.listar_auditoria(conn, tenant_id=None, actor_id=ctx.identidad_id, limite=limite)}
