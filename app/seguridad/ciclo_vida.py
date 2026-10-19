"""Ciclo de vida de las personas (fase 6, ciclo-vida-usuarios §8–§15).

Rutas de administración protegidas por `autorizar_ruta` (módulo IDENTIDADES) más las
de "mi cuenta" que cualquier persona con sesión usa sobre sí misma.

Reglas transversales:
- nadie modifica, amplía ni recupera su propio acceso desde la administración;
- sólo el director otorga roles globales y lo hace con reautenticación inmediata (C3);
- reducir acceso cierra al instante las sesiones afectadas; ampliarlo exige motivo y
  avisa a la persona y al director;
- cada operación queda en la bitácora y, cuando corresponde, se notifica.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import get_settings
from app.errors import DomainError
from app.seguridad import control, keycloak_admin, notificaciones, sesiones
from app.seguridad.politica import ROLES_GLOBALES, ROLES_PRIVILEGIADOS, Nivel

router = APIRouter(tags=["seguridad"])

ESPERA_RECUPERACION = timedelta(hours=24)


class Motivo(BaseModel):
    motivo: str = Field(min_length=5, max_length=300)


class AlcanceRequest(BaseModel):
    restaurantes: list[str] | None = None
    sucursales: list[str] | None = None
    modulos: list[str] | None = None
    condicionados: list[str] = Field(default_factory=list)
    vigente_hasta: datetime | None = None
    motivo: str = Field(min_length=5, max_length=300)


class AsignacionRequest(AlcanceRequest):
    rol: Literal[
        "CONSULTORA_DIRECTOR", "CONSULTORA_SEGURIDAD", "CONSULTORA_CAPTURISTA", "SOPORTE_TECNICO",
        "CLIENTE_RESPONSABLE", "CLIENTE_FINANZAS", "CLIENTE_OPERADOR",
    ]


class RecuperacionRequest(Motivo):
    verificacion: str = Field(min_length=5, max_length=300, description="Cómo se verificó la identidad por un canal previo")


# --------------------------------------------------------------------------- #
# Utilidades


def _ctx(request: Request) -> sesiones.Contexto:
    return request.state.contexto


def _persona(conn, identidad_id: UUID) -> dict:
    ident = control.identidad(conn, identidad_id)
    if ident is None:
        raise DomainError("Persona no encontrada.", 404)
    return ident


def _no_a_si_mismo(ctx: sesiones.Contexto, identidad_id: UUID) -> None:
    if ctx.identidad_id == identidad_id:
        raise DomainError("No puede modificar su propio acceso: otra persona administradora debe hacerlo.", 403)


def _exigir_reciente(ctx: sesiones.Contexto, nivel: Nivel) -> None:
    if not ctx.reciente(nivel):
        raise HTTPException(401, {"codigo": "REAUTENTICACION_REQUERIDA", "nivel": nivel.name,
                                  "mensaje": "Confirme su identidad de nuevo para esta operación."})


def _validar_alcance(conn, tenant_id: UUID, datos: AlcanceRequest) -> None:
    validos_r = {r["clave"] for r in control.restaurantes_tenant(conn, tenant_id)}
    validos_s = {s["clave"] for s in control.sucursales_tenant(conn, tenant_id)}
    if set(datos.restaurantes or []) - validos_r or set(datos.sucursales or []) - validos_s:
        raise DomainError("Restaurante o sucursal fuera de este cliente.", 422)


def _evento(conn, ctx: sesiones.Contexto, request: Request, tipo: str, identidad_id: UUID, *, motivo: str | None = None,
            sensibilidad: str = "C2", resultado: str = "EXITO", **detalle) -> None:
    control.registrar_evento(
        conn, tipo, resultado, actor_id=ctx.identidad_id, rol=ctx.rol, tenant_id=ctx.tenant_id, modulo="IDENTIDADES",
        accion="ADMINISTRAR", recurso_tipo="identidad", recurso_id=str(identidad_id), sesion_id=ctx.sesion_id,
        ip=control.ip_cliente(request), motivo=motivo, sensibilidad=sensibilidad, detalle=detalle,
    )


def _cerrar_sesiones(conn, ident: dict, motivo: str, *, asignacion_id: UUID | None = None) -> int:
    if asignacion_id is not None:
        cerradas = conn.execute(
            "UPDATE control.sesiones SET revocada_en = now(), motivo_revocacion = %s "
            "WHERE asignacion_id = %s AND revocada_en IS NULL",
            (motivo, asignacion_id),
        ).rowcount
    else:
        cerradas = sesiones.revocar_todas(conn, ident["id"], motivo)
    if ident["idp_subject"]:
        keycloak_admin.cerrar_sesiones(ident["idp_subject"])
    return cerradas


def _alcance_actual(conn, asignacion_id: UUID) -> dict:
    fila = conn.execute(
        """SELECT a.*, al.sucursales, al.restaurantes FROM control.asignaciones a
           JOIN control.alcance_asignacion al ON al.asignacion_id = a.id WHERE a.id = %s""",
        (asignacion_id,),
    ).fetchone()
    if fila is None:
        raise DomainError("Asignación no encontrada.", 404)
    return fila


def _efectivas(conn, tenant_id: UUID, restaurantes: list[str] | None, sucursales: list[str] | None) -> set[str] | None:
    """Sucursales que resultan de un alcance (None = todas)."""
    if not restaurantes and not sucursales:
        return None
    por_restaurante = {
        s["clave"] for s in control.sucursales_tenant(conn, tenant_id) if s["restaurante_clave"] in set(restaurantes or [])
    }
    return por_restaurante | set(sucursales or [])


def _es_reduccion(antes: dict, despues_sucursales: set[str] | None, datos: AlcanceRequest) -> bool:
    def incluido(nuevo, viejo) -> bool:  # None = todo
        return viejo is None or (nuevo is not None and set(nuevo) <= set(viejo))

    return (
        incluido(despues_sucursales, antes["sucursales"])
        and incluido(datos.modulos, antes["modulos"])
        and set(datos.condicionados) <= set(antes["condicionados"] or [])
        and (antes["vigente_hasta"] is None or (datos.vigente_hasta is not None and datos.vigente_hasta <= antes["vigente_hasta"]))
    )


def _texto_alcance(rol: str, restaurantes, sucursales) -> str:
    alcance = ", ".join([*(restaurantes or []), *(sucursales or [])]) or "todas las sucursales"
    return f"{rol} ({alcance})"


# --------------------------------------------------------------------------- #
# Ficha de la persona


@router.get("/api/v1/seguridad/identidades/{identidad_id}")
def ficha(identidad_id: UUID, request: Request):
    with control.conexion_control() as conn:
        ident = _persona(conn, identidad_id)
        asignaciones = conn.execute(
            """SELECT a.id, a.rol, a.estado, a.modulos, a.condicionados, a.vigente_desde, a.vigente_hasta, a.motivo,
                      a.creado_en, a.revocado_en, t.clave AS tenant, al.sucursales, al.restaurantes
               FROM control.asignaciones a
               JOIN control.alcance_asignacion al ON al.asignacion_id = a.id
               LEFT JOIN control.tenants t ON t.id = a.tenant_id
               WHERE a.identidad_id = %s ORDER BY a.estado = 'ACTIVA' DESC, a.creado_en DESC""",
            (identidad_id,),
        ).fetchall()
        sesiones_abiertas = conn.execute(
            """SELECT id, creada_en, ultimo_uso, metodo_auth, rol_activo, agente FROM control.sesiones
               WHERE identidad_id = %s AND revocada_en IS NULL AND expira_absoluta > now() ORDER BY creada_en DESC""",
            (identidad_id,),
        ).fetchall()
        recuperaciones = conn.execute(
            "SELECT id, solicitada_en, ejecutable_desde, estado, motivo FROM control.recuperaciones "
            "WHERE identidad_id = %s ORDER BY solicitada_en DESC LIMIT 5",
            (identidad_id,),
        ).fetchall()
    try:
        autenticadores = keycloak_admin.autenticadores(ident["idp_subject"]) if ident["idp_subject"] else []
        error_idp = None
    except DomainError:  # el proveedor puede no responder: la ficha se muestra igual
        autenticadores, error_idp = [], "No se pudieron leer los autenticadores del proveedor de identidad."
    return {
        "identidad": {k: ident[k] for k in ("id", "correo", "nombre", "estado", "motivo_estado", "creado_en",
                                            "ultimo_acceso_en", "requiere_nuevo_autenticador")},
        "asignaciones": asignaciones,
        "sesiones": sesiones_abiertas,
        "autenticadores": autenticadores,
        "autenticadores_error": error_idp,
        "recuperaciones": recuperaciones,
        "es_tu_cuenta": ident["id"] == _ctx(request).identidad_id,
    }


# --------------------------------------------------------------------------- #
# Asignaciones (§8)


@router.post("/api/v1/seguridad/identidades/{identidad_id}/asignaciones", status_code=201)
def agregar_asignacion(identidad_id: UUID, datos: AsignacionRequest, request: Request):
    ctx = _ctx(request)
    _no_a_si_mismo(ctx, identidad_id)
    global_ = datos.rol in ROLES_GLOBALES
    if global_ and ctx.rol != "CONSULTORA_DIRECTOR":
        raise DomainError("Sólo el director otorga roles globales.", 403)
    if global_:
        _exigir_reciente(ctx, Nivel.C3)  # AS-17
    with control.conexion_control() as conn:
        ident = _persona(conn, identidad_id)
        if ident["estado"] in ("BAJA_DEFINITIVA",):
            raise DomainError("La persona está dada de baja: use reingreso.", 409)
        if not global_:
            _validar_alcance(conn, ctx.tenant_id, datos)
        fila = conn.execute(
            """INSERT INTO control.asignaciones (identidad_id, rol, tenant_id, modulos, condicionados, vigente_hasta, motivo, creado_por)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (identidad_id, datos.rol, None if global_ else ctx.tenant_id, datos.modulos, datos.condicionados,
             datos.vigente_hasta, datos.motivo, ctx.identidad_id),
        ).fetchone()
        if not global_:
            control.guardar_alcance(conn, fila["id"], ctx.tenant_id, datos.restaurantes, datos.sucursales)
        if datos.rol in ROLES_PRIVILEGIADOS and ident["idp_subject"]:
            keycloak_admin.fijar_llave_fisica(ident["idp_subject"], True)
        detalle = _texto_alcance(datos.rol, datos.restaurantes, datos.sucursales)
        _evento(conn, ctx, request, "AMPLIACION_ACCESO", identidad_id, motivo=datos.motivo,
                sensibilidad="C3" if global_ else "C2", asignacion=str(fila["id"]), rol=datos.rol,
                restaurantes=datos.restaurantes, sucursales=datos.sucursales, condicionados=datos.condicionados)
        notificaciones.a_persona(conn, ident, "AMPLIACION_ACCESO", detalle=detalle)
        notificaciones.a_directores(conn, "AMPLIACION_ACCESO_DIRECTOR", excepto=ctx.identidad_id,
                                    nombre=ident["nombre"], detalle=detalle)
    return {"asignacion_id": str(fila["id"])}


@router.put("/api/v1/seguridad/asignaciones/{asignacion_id}")
def cambiar_alcance(asignacion_id: UUID, datos: AlcanceRequest, request: Request):
    ctx = _ctx(request)
    with control.conexion_control() as conn:
        antes = _alcance_actual(conn, asignacion_id)
        _no_a_si_mismo(ctx, antes["identidad_id"])
        if antes["estado"] != "ACTIVA":
            raise DomainError("Sólo se modifican asignaciones activas.", 409)
        if antes["tenant_id"] is None:
            raise DomainError("Los roles globales no tienen alcance por sucursal.", 422)
        _validar_alcance(conn, antes["tenant_id"], datos)
        despues = _efectivas(conn, antes["tenant_id"], datos.restaurantes, datos.sucursales)
        reduccion = _es_reduccion(antes, despues, datos)
        conn.execute(
            "UPDATE control.asignaciones SET modulos = %s, condicionados = %s, vigente_hasta = %s, motivo = %s WHERE id = %s",
            (datos.modulos, datos.condicionados, datos.vigente_hasta, datos.motivo, asignacion_id),
        )
        conn.execute("DELETE FROM control.asignacion_restaurantes WHERE asignacion_id = %s", (asignacion_id,))
        conn.execute("DELETE FROM control.asignacion_sucursales WHERE asignacion_id = %s", (asignacion_id,))
        control.guardar_alcance(conn, asignacion_id, antes["tenant_id"], datos.restaurantes, datos.sucursales)
        ident = _persona(conn, antes["identidad_id"])
        if reduccion:
            # §8.1: efecto inmediato sobre las sesiones que usan esta asignación.
            cerradas = _cerrar_sesiones(conn, ident, "Reducción de acceso", asignacion_id=asignacion_id)
            _evento(conn, ctx, request, "REDUCCION_ACCESO", ident["id"], motivo=datos.motivo, asignacion=str(asignacion_id),
                    sesiones_revocadas=cerradas)
            notificaciones.a_persona(conn, ident, "REDUCCION_ACCESO")
        else:
            detalle = _texto_alcance(antes["rol"], datos.restaurantes, datos.sucursales)
            _evento(conn, ctx, request, "AMPLIACION_ACCESO", ident["id"], motivo=datos.motivo, asignacion=str(asignacion_id),
                    restaurantes=datos.restaurantes, sucursales=datos.sucursales, condicionados=datos.condicionados)
            notificaciones.a_persona(conn, ident, "AMPLIACION_ACCESO", detalle=detalle)
            notificaciones.a_directores(conn, "AMPLIACION_ACCESO_DIRECTOR", excepto=ctx.identidad_id,
                                        nombre=ident["nombre"], detalle=detalle)
    return {"tipo": "REDUCCION" if reduccion else "AMPLIACION"}


@router.post("/api/v1/seguridad/asignaciones/{asignacion_id}/revocar")
def revocar_asignacion(asignacion_id: UUID, datos: Motivo, request: Request):
    ctx = _ctx(request)
    with control.conexion_control() as conn:
        antes = _alcance_actual(conn, asignacion_id)
        _no_a_si_mismo(ctx, antes["identidad_id"])
        if antes["rol"] in ROLES_GLOBALES and ctx.rol != "CONSULTORA_DIRECTOR":
            raise DomainError("Sólo el director retira roles globales.", 403)
        conn.execute(
            "UPDATE control.asignaciones SET estado = 'REVOCADA', revocado_en = now() WHERE id = %s AND estado <> 'REVOCADA'",
            (asignacion_id,),
        )
        ident = _persona(conn, antes["identidad_id"])
        cerradas = _cerrar_sesiones(conn, ident, "Asignación revocada", asignacion_id=asignacion_id)
        _evento(conn, ctx, request, "REVOCACION_ASIGNACION", ident["id"], motivo=datos.motivo,
                asignacion=str(asignacion_id), rol=antes["rol"], sesiones_revocadas=cerradas)
        notificaciones.a_persona(conn, ident, "REDUCCION_ACCESO")
    return {"sesiones_revocadas": cerradas}


# --------------------------------------------------------------------------- #
# Estado de la cuenta (§11, §14, §15)


@router.post("/api/v1/seguridad/identidades/{identidad_id}/reactivar")
def reactivar(identidad_id: UUID, datos: Motivo, request: Request):
    ctx = _ctx(request)
    _no_a_si_mismo(ctx, identidad_id)
    with control.conexion_control() as conn:
        ident = _persona(conn, identidad_id)
        if ident["estado"] not in ("SUSPENDIDA", "BLOQUEADA_SEGURIDAD"):
            raise DomainError("Sólo se reactivan cuentas suspendidas o bloqueadas.", 409)
        conn.execute(
            "UPDATE control.identidades SET estado = 'ACTIVA', motivo_estado = %s, aviso_inactividad_en = NULL, "
            "ultimo_acceso_en = now(), actualizado_en = now() WHERE id = %s",
            (datos.motivo, identidad_id),
        )
        if ident["idp_subject"]:
            keycloak_admin.habilitar(ident["idp_subject"])
        _evento(conn, ctx, request, "REACTIVACION", identidad_id, motivo=datos.motivo, estado_anterior=ident["estado"])
        notificaciones.a_persona(conn, ident, "REACTIVACION")
    return {"estado": "ACTIVA"}


@router.post("/api/v1/seguridad/identidades/{identidad_id}/baja")
def baja(identidad_id: UUID, datos: Motivo, request: Request):
    """Baja de colaborador en una sola operación (§14). Objetivo: menos de 15 minutos."""
    ctx = _ctx(request)
    _no_a_si_mismo(ctx, identidad_id)
    inicio = time.monotonic()
    pasos: dict[str, int | str] = {}
    with control.conexion_control() as conn:
        ident = _persona(conn, identidad_id)
        if ident["estado"] == "BAJA_DEFINITIVA":
            raise DomainError("La persona ya está dada de baja.", 409)
        conn.execute(
            "UPDATE control.identidades SET estado = 'BAJA_DEFINITIVA', motivo_estado = %s, actualizado_en = now() WHERE id = %s",
            (datos.motivo, identidad_id),
        )
        pasos["sesiones_revocadas"] = sesiones.revocar_todas(conn, identidad_id, "Baja definitiva")
        pasos["asignaciones_revocadas"] = conn.execute(
            "UPDATE control.asignaciones SET estado = 'REVOCADA', revocado_en = now() "
            "WHERE identidad_id = %s AND estado IN ('ACTIVA', 'PENDIENTE', 'SUSPENDIDA')",
            (identidad_id,),
        ).rowcount
        pasos["recuperaciones_canceladas"] = conn.execute(
            "UPDATE control.recuperaciones SET estado = 'CANCELADA', resuelta_en = now(), resuelta_por = %s "
            "WHERE identidad_id = %s AND estado = 'PENDIENTE'",
            (ctx.identidad_id, identidad_id),
        ).rowcount
        if ident["idp_subject"]:
            pasos["autenticadores_revocados"] = keycloak_admin.eliminar_todos_los_autenticadores(ident["idp_subject"])
            keycloak_admin.deshabilitar(ident["idp_subject"])
        # Verificación: ninguna sesión vigente ni asignación activa queda en pie.
        restantes = conn.execute(
            """SELECT (SELECT count(*) FROM control.sesiones WHERE identidad_id = %s AND revocada_en IS NULL) AS sesiones,
                      (SELECT count(*) FROM control.asignaciones WHERE identidad_id = %s AND estado = 'ACTIVA') AS asignaciones""",
            (identidad_id, identidad_id),
        ).fetchone()
        pasos["verificacion"] = "ok" if restantes["sesiones"] == 0 and restantes["asignaciones"] == 0 else "FALLÓ"
        pasos["segundos"] = round(time.monotonic() - inicio, 2)
        _evento(conn, ctx, request, "BAJA", identidad_id, motivo=datos.motivo, sensibilidad="C2", **pasos)
        notificaciones.a_directores(conn, "BAJA_DIRECTOR", nombre=ident["nombre"])
    if pasos["verificacion"] != "ok":
        raise DomainError("La baja no pudo verificarse; revise la bitácora.", 500)
    return pasos


@router.post("/api/v1/seguridad/identidades/{identidad_id}/reingreso")
def reingreso(identidad_id: UUID, datos: Motivo, request: Request):
    """Reingreso (§15): nueva invitación, sin restaurar asignaciones antiguas."""
    ctx = _ctx(request)
    _no_a_si_mismo(ctx, identidad_id)
    with control.conexion_control() as conn:
        ident = _persona(conn, identidad_id)
        if ident["estado"] != "BAJA_DEFINITIVA":
            raise DomainError("Sólo se reincorpora a personas dadas de baja.", 409)
        conn.execute(
            "UPDATE control.identidades SET estado = 'INVITADA', motivo_estado = %s, requiere_nuevo_autenticador = false, "
            "actualizado_en = now() WHERE id = %s",
            (datos.motivo, identidad_id),
        )
        if ident["idp_subject"]:
            keycloak_admin.eliminar_todos_los_autenticadores(ident["idp_subject"])
            keycloak_admin.fijar_llave_fisica(ident["idp_subject"], False)
            keycloak_admin.habilitar(ident["idp_subject"])
            keycloak_admin.enviar_invitacion(ident["idp_subject"], llave_fisica=False)
        _evento(conn, ctx, request, "REINGRESO", identidad_id, motivo=datos.motivo)
    return {"estado": "INVITADA", "nota": "Agregue sus nuevas asignaciones; las anteriores no se restauran."}


# --------------------------------------------------------------------------- #
# Autenticadores (§9)


@router.post("/api/v1/seguridad/identidades/{identidad_id}/autenticadores/{credencial_id}/perdido")
def marcar_perdido(identidad_id: UUID, credencial_id: str, datos: Motivo, request: Request):
    ctx = _ctx(request)
    with control.conexion_control() as conn:
        ident = _persona(conn, identidad_id)
        return _dar_de_baja_autenticador(conn, ctx, request, ident, credencial_id, datos.motivo, propio=False)


def _dar_de_baja_autenticador(conn, ctx, request, ident: dict, credencial_id: str, motivo: str, *, propio: bool) -> dict:
    if not ident["idp_subject"]:
        raise DomainError("La persona no tiene cuenta en el proveedor de identidad.", 409)
    lista = keycloak_admin.autenticadores(ident["idp_subject"])
    cred = next((c for c in lista if c["id"] == credencial_id), None)
    if cred is None:
        raise DomainError("Autenticador no encontrado.", 404)
    fuertes_restantes = [c for c in lista if c["id"] != credencial_id and c["tipo"] in ("webauthn", "webauthn-passwordless")]
    if propio and not fuertes_restantes:
        raise DomainError("Registre otro autenticador antes de dar de baja el último.", 409)
    keycloak_admin.eliminar_autenticador(ident["idp_subject"], credencial_id)
    cerradas = _cerrar_sesiones(conn, ident, "Autenticador perdido")
    _evento(conn, ctx, request, "AUTENTICADOR_PERDIDO", ident["id"], motivo=motivo, sensibilidad="ALERTA",
            autenticador=cred["tipo"], etiqueta=cred["etiqueta"], sesiones_revocadas=cerradas, propio=propio,
            sin_autenticador_fuerte=not fuertes_restantes)
    notificaciones.a_persona(conn, ident, "AUTENTICADOR_PERDIDO", detalle=f"{cred['tipo_nombre']} {cred['etiqueta'] or ''}".strip())
    return {"sesiones_revocadas": cerradas, "autenticadores_fuertes_restantes": len(fuertes_restantes)}


@router.get("/api/v1/seguridad/mi-cuenta")
def mi_cuenta(request: Request):
    with control.conexion_control() as conn:
        ctx = _sesion_propia(request, conn)
        ident = _persona(conn, ctx.identidad_id)
    try:
        autenticadores = keycloak_admin.autenticadores(ident["idp_subject"]) if ident["idp_subject"] else []
        error_idp = None
    except DomainError:
        autenticadores, error_idp = [], "No se pudieron leer tus autenticadores; intenta más tarde."
    return {
        "autenticadores": autenticadores,
        "autenticadores_error": error_idp,
        "requiere_nuevo_autenticador": ident["requiere_nuevo_autenticador"],
    }


@router.post("/api/v1/seguridad/mi-cuenta/autenticadores/{credencial_id}/perdido")
def mi_autenticador_perdido(credencial_id: str, datos: Motivo, request: Request):
    with control.conexion_control() as conn:
        ctx = _sesion_propia(request, conn)
        _exigir_reciente(ctx, Nivel.C2)
        return _dar_de_baja_autenticador(conn, ctx, request, _persona(conn, ctx.identidad_id), credencial_id,
                                         datos.motivo, propio=True)


def _sesion_propia(request: Request, conn) -> sesiones.Contexto:
    tenant = control.tenant_por_clave(conn, get_settings().tenant_clave)
    ctx, _ = sesiones.resolver(conn, request.cookies.get(sesiones.COOKIE), tenant) if tenant else (None, None)
    if ctx is None:
        raise DomainError("Inicie sesión para continuar.", 401)
    return ctx


# --------------------------------------------------------------------------- #
# Recuperación asistida (§10)


@router.post("/api/v1/seguridad/identidades/{identidad_id}/recuperacion", status_code=201)
def solicitar_recuperacion(identidad_id: UUID, datos: RecuperacionRequest, request: Request):
    ctx = _ctx(request)
    _no_a_si_mismo(ctx, identidad_id)
    with control.conexion_control() as conn:
        ident = _persona(conn, identidad_id)
        privilegiada = any(a["privilegiado"] for a in control.asignaciones_vigentes(conn, identidad_id))
        if privilegiada:
            # §10.2: procedimiento reforzado; soporte o seguridad no recuperan cuentas privilegiadas.
            if ctx.rol != "CONSULTORA_DIRECTOR":
                raise DomainError("Sólo otro director recupera una cuenta privilegiada.", 403)
            _exigir_reciente(ctx, Nivel.C3)
        if ident["estado"] in ("BAJA_DEFINITIVA",):
            raise DomainError("La persona está dada de baja: use reingreso.", 409)
        ahora = datetime.now(timezone.utc)
        fila = conn.execute(
            """INSERT INTO control.recuperaciones (identidad_id, solicitada_por, motivo, verificacion, solicitada_en, ejecutable_desde)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, ejecutable_desde""",
            (identidad_id, ctx.identidad_id, datos.motivo, datos.verificacion, ahora, ahora + ESPERA_RECUPERACION),
        ).fetchone()
        cerradas = _cerrar_sesiones(conn, ident, "Recuperación asistida solicitada")
        _evento(conn, ctx, request, "RECUPERACION_SOLICITADA", identidad_id, motivo=datos.motivo,
                sensibilidad="C3" if privilegiada else "C2", verificacion=datos.verificacion,
                recuperacion=str(fila["id"]), sesiones_revocadas=cerradas)
        notificaciones.a_persona(conn, ident, "RECUPERACION_SOLICITADA",
                                 detalle=fila["ejecutable_desde"].astimezone().strftime("%d/%m/%Y %H:%M"))
    return {"recuperacion_id": str(fila["id"]), "ejecutable_desde": fila["ejecutable_desde"].isoformat()}


@router.post("/api/v1/seguridad/recuperaciones/{recuperacion_id}/ejecutar")
def ejecutar_recuperacion(recuperacion_id: UUID, request: Request):
    ctx = _ctx(request)
    with control.conexion_control() as conn:
        rec = conn.execute("SELECT * FROM control.recuperaciones WHERE id = %s", (recuperacion_id,)).fetchone()
        if rec is None or rec["estado"] != "PENDIENTE":
            raise DomainError("No hay una recuperación pendiente con ese identificador.", 404)
        _no_a_si_mismo(ctx, rec["identidad_id"])
        if datetime.now(timezone.utc) < rec["ejecutable_desde"]:
            raise DomainError("La espera de seguridad de 24 horas todavía no termina.", 409)
        ident = _persona(conn, rec["identidad_id"])
        privilegiada = any(a["privilegiado"] for a in control.asignaciones_vigentes(conn, ident["id"]))
        if privilegiada:
            if ctx.rol != "CONSULTORA_DIRECTOR":
                raise DomainError("Sólo otro director recupera una cuenta privilegiada.", 403)
            _exigir_reciente(ctx, Nivel.C3)
        revocados = keycloak_admin.eliminar_todos_los_autenticadores(ident["idp_subject"]) if ident["idp_subject"] else 0
        cerradas = _cerrar_sesiones(conn, ident, "Recuperación asistida ejecutada")
        conn.execute(
            "UPDATE control.identidades SET estado = 'REGISTRO_PENDIENTE', requiere_nuevo_autenticador = false, "
            "actualizado_en = now() WHERE id = %s",
            (ident["id"],),
        )
        conn.execute(
            "UPDATE control.recuperaciones SET estado = 'EJECUTADA', resuelta_en = now(), resuelta_por = %s WHERE id = %s",
            (ctx.identidad_id, recuperacion_id),
        )
        if ident["idp_subject"]:
            keycloak_admin.enviar_invitacion(ident["idp_subject"], llave_fisica=privilegiada)
        _evento(conn, ctx, request, "RECUPERACION_EJECUTADA", ident["id"], motivo=rec["motivo"],
                sensibilidad="C3" if privilegiada else "C2", recuperacion=str(recuperacion_id),
                autenticadores_revocados=revocados, sesiones_revocadas=cerradas)
        notificaciones.a_persona(conn, ident, "RECUPERACION_EJECUTADA")
    return {"estado": "REGISTRO_PENDIENTE", "autenticadores_revocados": revocados}


@router.post("/api/v1/seguridad/recuperaciones/{recuperacion_id}/cancelar")
def cancelar_recuperacion(recuperacion_id: UUID, datos: Motivo, request: Request):
    ctx = _ctx(request)
    with control.conexion_control() as conn:
        rec = conn.execute(
            "UPDATE control.recuperaciones SET estado = 'CANCELADA', resuelta_en = now(), resuelta_por = %s "
            "WHERE id = %s AND estado = 'PENDIENTE' RETURNING identidad_id",
            (ctx.identidad_id, recuperacion_id),
        ).fetchone()
        if rec is None:
            raise DomainError("No hay una recuperación pendiente con ese identificador.", 404)
        _evento(conn, ctx, request, "RECUPERACION_CANCELADA", rec["identidad_id"], motivo=datos.motivo,
                recuperacion=str(recuperacion_id))
    return {"estado": "CANCELADA"}
