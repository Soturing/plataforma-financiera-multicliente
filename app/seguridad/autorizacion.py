"""Autorización en el servidor para cada ruta (matriz-permisos §1, fase 4).

`autorizar_ruta` es una dependencia global de la app: se ejecuta antes de cada
endpoint, busca la clasificación de la ruta en `politica.RUTAS` y deniega por
defecto lo que no esté clasificado o permitido.
"""
from __future__ import annotations

import json
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute

from app.config import get_settings
from app.database import identidad_actual, rls_verificado, sucursales_actuales
from app.seguridad import control, sesiones
from app.seguridad.politica import MODULOS_SIEMPRE_CON_SESION, RUTAS, Nivel, permitido

# Autor de la operación en curso (etiqueta de la sesión) o None si no hay sesión
# en modo abierto. Lo leen los endpoints con `actor_o`.
actor_actual: ContextVar[str | None] = ContextVar("actor_actual", default=None)


def actor_o(valor: str) -> str:
    """Autor que se guarda en la base de negocio: el de la sesión, nunca el del navegador (D-014)."""
    return actor_actual.get() or valor


@dataclass
class _Decision:
    error: HTTPException | None = None


def _error(status: int, codigo: str, mensaje: str, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"codigo": codigo, "mensaje": mensaje, **extra})


async def _sucursal_solicitada(request: Request, parametro: str | None, conn) -> str | None:
    """Sucursal que pide la petición (query, formulario o JSON), traducida a su clave."""
    valor = request.query_params.get(parametro) if parametro else None
    tipo = request.headers.get("content-type", "")
    if valor is None and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if tipo.startswith("multipart/form-data") or tipo.startswith("application/x-www-form-urlencoded"):
            valor = (await request.form()).get("sucursal_clave")
        elif tipo.startswith("application/json"):
            cuerpo = await request.json()
            if isinstance(cuerpo, dict):
                valor = cuerpo.get("sucursal_clave")
                if valor is None and cuerpo.get("sucursal_id"):
                    fila = conn.execute(
                        "SELECT clave FROM control.sucursales WHERE data_plane_id::text = %s", (str(cuerpo["sucursal_id"]),)
                    ).fetchone()
                    valor = fila["clave"] if fila else "__desconocida__"
    return valor or None


async def _sustituir_autor(request: Request, etiqueta: str) -> None:
    """Pone la identidad de la sesión en todos los campos `*_por` del JSON recibido."""
    if not request.headers.get("content-type", "").startswith("application/json"):
        return
    try:
        cuerpo = await request.json()
    except json.JSONDecodeError:
        return
    if isinstance(cuerpo, dict):
        for clave in list(cuerpo):
            if clave.endswith("_por"):
                cuerpo[clave] = etiqueta


async def autorizar_ruta(request: Request) -> None:
    actor_actual.set(None)
    identidad_actual.set(None)
    sucursales_actuales.set("*")
    ruta = request.scope.get("route")
    if not isinstance(ruta, APIRoute):
        return
    metodo = "GET" if request.method == "HEAD" else request.method
    regla = RUTAS.get((metodo, ruta.path))
    if regla is None:
        raise _error(403, "RUTA_SIN_CLASIFICAR", "Operación no permitida.")
    if regla.modulo is None:
        return

    settings = get_settings()
    abierto = settings.acceso_modo == "abierto" and regla.modulo not in MODULOS_SIEMPRE_CON_SESION
    if not control.control_configurado():
        if abierto:
            return
        raise _error(503, "CONTROL_NO_CONFIGURADO", "El control de acceso no está configurado.")

    decision = _Decision()
    ctx = None
    alcance_rls = "*"
    with control.conexion_control() as conn:
        tenant = control.tenant_por_clave(conn, settings.tenant_clave)
        if tenant is None:
            if abierto:
                return
            raise _error(503, "INSTALACION_PENDIENTE", "Falta registrar este cliente en el plano de control.")

        token = request.cookies.get(sesiones.COOKIE)
        ctx, motivo = sesiones.resolver(conn, token, tenant)
        ip = control.ip_cliente(request)
        peticion = request.headers.get("x-request-id") or uuid.uuid4().hex

        if ctx is None:
            if motivo == "otro_tenant":
                control.registrar_evento(
                    conn, "INTENTO_ENTRE_TENANTS", "RECHAZO", actor_tipo="ANONIMO", tenant_id=tenant["id"],
                    ip=ip, peticion_id=peticion, sensibilidad="ALERTA", detalle={"ruta": ruta.path},
                )
            if motivo == "revocada":
                control.registrar_evento(
                    conn, "SESION_REVOCADA_REUTILIZADA", "RECHAZO", actor_tipo="ANONIMO", tenant_id=tenant["id"],
                    ip=ip, peticion_id=peticion, sensibilidad="ALERTA", detalle={"ruta": ruta.path},
                )
            if not abierto:
                decision.error = _error(401, "SESION_REQUERIDA", "Inicie sesión para continuar.", motivo=motivo)
        elif ctx.asignacion_id is None:
            decision.error = _error(409, "CONTEXTO_REQUERIDO", "Seleccione el cliente y el rol con los que trabajará.")
        elif ctx.requiere_nuevo_autenticador:
            # Entró con un código de recuperación: primero registra un autenticador nuevo (§10.1).
            decision.error = _error(403, "AUTENTICADOR_PENDIENTE", "Registre una passkey nueva antes de continuar.",
                                    url="/auth/registrar-autenticador")
        elif not permitido(ctx.rol, regla.modulo, regla.accion, modulos_asignados=ctx.modulos, condicionados=ctx.condicionados):
            decision.error = _error(403, "SIN_PERMISO", "Su rol no permite esta operación.", modulo=regla.modulo, accion=regla.accion)
        else:
            sucursal = await _sucursal_solicitada(request, regla.sucursal_param, conn)
            if ctx.sucursales is not None:
                if sucursal is not None and sucursal not in ctx.sucursales:
                    decision.error = _error(403, "SUCURSAL_FUERA_DE_ALCANCE", "La sucursal no está en su asignación.")
                elif sucursal is None and regla.sucursal_param is not None and not rls_verificado():
                    # Sin RLS efectivo en la base, un consolidado incluiría sucursales ajenas.
                    decision.error = _error(
                        403, "CONSOLIDADO_NO_PERMITIDO",
                        "Su asignación está limitada a algunas sucursales: seleccione una de ellas.",
                        sucursales=ctx.sucursales,
                    )
            if decision.error is None and not ctx.reciente(regla.nivel):
                decision.error = _error(
                    401, "REAUTENTICACION_REQUERIDA",
                    "Esta operación requiere confirmar su identidad de nuevo.", nivel=regla.nivel.name,
                )

        if ctx is not None:
            recurso = next(iter(request.path_params.values()), None)
            if decision.error is not None:
                control.registrar_evento(
                    conn, "ACCESO_DENEGADO", "RECHAZO", actor_id=ctx.identidad_id, rol=ctx.rol, tenant_id=tenant["id"],
                    modulo=regla.modulo, accion=regla.accion, recurso_tipo=ruta.path, recurso_id=str(recurso) if recurso else None,
                    sesion_id=ctx.sesion_id, metodo_auth=ctx.metodo_auth, ip=ip, peticion_id=peticion,
                    politica=decision.error.detail["codigo"], detalle={"metodo": metodo},
                )
            elif regla.nivel >= Nivel.C1:
                control.registrar_evento(
                    conn, "OPERACION_AUTORIZADA", actor_id=ctx.identidad_id, rol=ctx.rol, tenant_id=tenant["id"],
                    modulo=regla.modulo, accion=regla.accion, recurso_tipo=ruta.path, recurso_id=str(recurso) if recurso else None,
                    sesion_id=ctx.sesion_id, metodo_auth=ctx.metodo_auth, ip=ip, peticion_id=peticion,
                    sensibilidad=regla.nivel.name, politica=f"{ctx.rol}:{regla.modulo}:{regla.accion}",
                    detalle={"metodo": metodo},
                )
            if decision.error is None and ctx.sucursales is not None:
                # RLS en la base del cliente: sólo las sucursales de la asignación (fase 5).
                alcance_rls = ",".join(control.ids_data_plane(conn, tenant["id"], ctx.sucursales))
    # La conexión ya confirmó la auditoría: ahora sí se puede rechazar.
    if decision.error is not None:
        raise decision.error
    if ctx is not None:
        request.state.contexto = ctx
        actor_actual.set(ctx.etiqueta)
        identidad_actual.set(str(ctx.identidad_id))
        sucursales_actuales.set(alcance_rls)
        await _sustituir_autor(request, ctx.etiqueta)
