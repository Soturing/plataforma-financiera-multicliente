"""La matriz de permisos y la clasificación de rutas (sin base de datos)."""
import inspect
import typing

from fastapi.routing import APIRoute
from pydantic import BaseModel

from app.main import app
from app.seguridad.politica import (
    APROBAR, CONSULTAR, ELIMINAR, EXPORTAR_CSV, EXPORTAR_PDF, MATRIZ, OPERAR, RUTAS, Nivel, permitido,
)

_FINANCIEROS = ("DOCUMENTOS", "COMPROBANTES", "PROVEEDORES", "CATALOGOS", "VENTAS", "FINANZAS", "REPORTES", "NOMINA")


def p(rol, modulo, accion, modulos=None, condicionados=()):
    return permitido(rol, modulo, accion, modulos_asignados=modulos, condicionados=list(condicionados))


def test_toda_ruta_de_la_api_esta_clasificada():
    rutas = {(m, r.path) for r in app.routes if isinstance(r, APIRoute) for m in r.methods}
    assert rutas - set(RUTAS) == set(), "Ruta nueva sin módulo, acción y nivel en politica.RUTAS"
    assert set(RUTAS) - rutas == set(), "Clasificación de una ruta que ya no existe"


def test_toda_ruta_que_recibe_sucursal_la_declara():
    """Sin `sucursal_param`, una ruta podría saltarse el filtro de sucursales de la asignación."""
    faltantes = []
    for r in app.routes:
        if not isinstance(r, APIRoute):
            continue
        nombres = {p.name for p in r.dependant.query_params + r.dependant.body_params}
        if "sucursal_clave" in nombres:
            for metodo in r.methods:
                if RUTAS[(metodo, r.path)].sucursal_param != "sucursal_clave":
                    faltantes.append((metodo, r.path))
    assert faltantes == []


def test_las_exportaciones_csv_son_criticas():
    for (metodo, ruta), regla in RUTAS.items():
        if regla.accion == EXPORTAR_CSV:
            assert regla.nivel == Nivel.C3, ruta


def test_administrador_de_seguridad_no_ve_contenido_financiero():
    for modulo in _FINANCIEROS:
        for accion in (CONSULTAR, OPERAR, APROBAR, EXPORTAR_PDF, EXPORTAR_CSV):
            assert not p("CONSULTORA_SEGURIDAD", modulo, accion), (modulo, accion)
    assert p("CONSULTORA_SEGURIDAD", "IDENTIDADES", "ADMINISTRAR")


def test_capturista_sin_permiso_individual_no_exporta_csv():
    assert not p("CONSULTORA_CAPTURISTA", "REPORTES", EXPORTAR_CSV)
    assert p("CONSULTORA_CAPTURISTA", "REPORTES", EXPORTAR_CSV, condicionados=["EXPORTAR_CSV"])
    assert p("CONSULTORA_CAPTURISTA", "REPORTES", EXPORTAR_PDF)


def test_capturista_opera_solo_los_modulos_asignados():
    assert p("CONSULTORA_CAPTURISTA", "DOCUMENTOS", APROBAR, modulos=["DOCUMENTOS"])
    assert not p("CONSULTORA_CAPTURISTA", "VENTAS", OPERAR, modulos=["DOCUMENTOS"])


def test_roles_del_cliente_no_administran_ni_aprueban_facturas():
    for rol in ("CLIENTE_RESPONSABLE", "CLIENTE_FINANZAS", "CLIENTE_OPERADOR"):
        assert not p(rol, "DOCUMENTOS", APROBAR)
        assert not p(rol, "DOCUMENTOS", ELIMINAR)
        assert not p(rol, "IDENTIDADES", "ADMINISTRAR")


def test_operador_no_aprueba_comprobantes_ni_ve_resultados_consolidados_sin_permiso():
    assert not p("CLIENTE_OPERADOR", "COMPROBANTES", APROBAR)
    assert not p("CLIENTE_OPERADOR", "NOMINA", CONSULTAR)
    assert p("CLIENTE_OPERADOR", "NOMINA", CONSULTAR, condicionados=["CONSULTAR_NOMINA"])


def test_soporte_e_integraciones_no_tocan_contenido():
    for modulo in _FINANCIEROS:
        assert not p("SOPORTE_TECNICO", modulo, CONSULTAR)
        assert not p("INTEGRACION_API", modulo, CONSULTAR)


def test_nadie_modifica_ni_elimina_la_auditoria():
    for rol, modulos in MATRIZ.items():
        acciones = modulos.get("AUDITORIA", frozenset())
        assert not acciones & {OPERAR, ELIMINAR, APROBAR, "ADMINISTRAR"}, rol


def _campos_autor_anidados(modelo, ruta="", vistos=None):
    vistos = vistos if vistos is not None else set()
    if modelo in vistos:
        return []
    vistos.add(modelo)
    hallados = []
    for nombre, campo in modelo.model_fields.items():
        for tipo in typing.get_args(campo.annotation) or (campo.annotation,):
            for interno in typing.get_args(tipo) or (tipo,):
                if isinstance(interno, type) and issubclass(interno, BaseModel):
                    hallados += [f"{ruta}{nombre}.{c}" for c in interno.model_fields if c.endswith("_por")]
                    hallados += _campos_autor_anidados(interno, f"{ruta}{nombre}.", vistos)
    return hallados


def test_el_autor_siempre_se_puede_sustituir_por_el_de_la_sesion():
    """`_sustituir_autor` sólo reemplaza los `*_por` del primer nivel del JSON y los formularios usan `actor_o`."""
    faltantes = []
    for r in app.routes:
        if not isinstance(r, APIRoute):
            continue
        for param in r.dependant.body_params:
            anotacion = param.field_info.annotation
            if isinstance(anotacion, type) and issubclass(anotacion, BaseModel):
                faltantes += [f"{r.path}: {c}" for c in _campos_autor_anidados(anotacion)]
            elif param.name.endswith("_por") and f"actor_o({param.name})" not in inspect.getsource(r.endpoint):
                faltantes.append(f"{r.path}: formulario {param.name} sin actor_o")
    assert faltantes == []
