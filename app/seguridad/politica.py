"""Política de autorización (D-009, D-011, D-012, D-013).

Traduce `docs/seguridad/matriz-permisos.md` a datos verificables:

- `MATRIZ`: qué acciones permite cada rol en cada módulo;
- `CONDICIONADAS`: acciones que, además, exigen un permiso explícito en la asignación;
- `RUTAS`: módulo, acción y nivel C0–C3 de cada ruta de la API. Una ruta sin
  clasificar falla en las pruebas: se deniega por defecto.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Nivel(IntEnum):
    C0 = 0  # operación ordinaria
    C1 = 1  # controlada: auditoría detallada
    C2 = 2  # sensible: autenticación reciente (15 min) y motivo cuando aplique
    C3 = 3  # crítica: reautenticación inmediata y motivo


# Acciones genéricas por módulo.
CONSULTAR = "CONSULTAR"
OPERAR = "OPERAR"            # cargar, capturar, corregir
APROBAR = "APROBAR"          # aprobar o rechazar
ELIMINAR = "ELIMINAR"        # eliminar pendientes, cancelar lotes, descartar duplicados
ADMINISTRAR = "ADMINISTRAR"  # catálogos estructurales, usuarios, políticas
EXPORTAR_PDF = "EXPORTAR_PDF"
EXPORTAR_CSV = "EXPORTAR_CSV"

ROLES_PRIVILEGIADOS = frozenset({"CONSULTORA_DIRECTOR", "CONSULTORA_SEGURIDAD"})
ROLES_GLOBALES = frozenset({"CONSULTORA_DIRECTOR", "CONSULTORA_SEGURIDAD", "SOPORTE_TECNICO"})

_FINANCIEROS = ("DOCUMENTOS", "COMPROBANTES", "PROVEEDORES", "CATALOGOS", "VENTAS", "FINANZAS", "REPORTES", "NOMINA")


def _todo(*acciones: str) -> frozenset[str]:
    return frozenset(acciones)


MATRIZ: dict[str, dict[str, frozenset[str]]] = {
    "CONSULTORA_DIRECTOR": {
        **{m: _todo(CONSULTAR, OPERAR, APROBAR, ELIMINAR, ADMINISTRAR, EXPORTAR_PDF, EXPORTAR_CSV) for m in _FINANCIEROS},
        "CLIENTES": _todo(CONSULTAR, ADMINISTRAR),
        "IDENTIDADES": _todo(CONSULTAR, ADMINISTRAR),
        "AUDITORIA": _todo(CONSULTAR, EXPORTAR_CSV),
        "OPERACION": _todo(CONSULTAR),
    },
    # Administra accesos; nunca contenido financiero (catalogo-roles §3).
    "CONSULTORA_SEGURIDAD": {
        "CLIENTES": _todo(CONSULTAR),
        "IDENTIDADES": _todo(CONSULTAR, ADMINISTRAR),
        "AUDITORIA": _todo(CONSULTAR),
    },
    "CONSULTORA_CAPTURISTA": {
        "DOCUMENTOS": _todo(CONSULTAR, OPERAR, APROBAR, ELIMINAR),
        "COMPROBANTES": _todo(CONSULTAR, OPERAR, APROBAR, EXPORTAR_PDF),
        "PROVEEDORES": _todo(CONSULTAR, OPERAR),
        "CATALOGOS": _todo(CONSULTAR),
        "VENTAS": _todo(CONSULTAR, OPERAR),
        "FINANZAS": _todo(CONSULTAR, OPERAR),
        "NOMINA": _todo(CONSULTAR, OPERAR),
        "REPORTES": _todo(CONSULTAR, EXPORTAR_PDF, EXPORTAR_CSV),
    },
    "CLIENTE_RESPONSABLE": {
        "DOCUMENTOS": _todo(CONSULTAR),
        "COMPROBANTES": _todo(CONSULTAR, OPERAR, APROBAR, EXPORTAR_PDF),
        "PROVEEDORES": _todo(CONSULTAR),
        "CATALOGOS": _todo(CONSULTAR),
        "VENTAS": _todo(CONSULTAR, OPERAR),
        "FINANZAS": _todo(CONSULTAR),
        "NOMINA": _todo(CONSULTAR),
        "REPORTES": _todo(CONSULTAR, EXPORTAR_PDF, EXPORTAR_CSV),
        "AUDITORIA": _todo(CONSULTAR),
    },
    "CLIENTE_FINANZAS": {
        "DOCUMENTOS": _todo(CONSULTAR),
        "COMPROBANTES": _todo(CONSULTAR, OPERAR, APROBAR, EXPORTAR_PDF),
        "PROVEEDORES": _todo(CONSULTAR),
        "CATALOGOS": _todo(CONSULTAR),
        "VENTAS": _todo(CONSULTAR, OPERAR),
        "FINANZAS": _todo(CONSULTAR, OPERAR),
        "NOMINA": _todo(CONSULTAR),
        "REPORTES": _todo(CONSULTAR, EXPORTAR_PDF, EXPORTAR_CSV),
    },
    "CLIENTE_OPERADOR": {
        "COMPROBANTES": _todo(CONSULTAR, OPERAR, EXPORTAR_PDF),
        "PROVEEDORES": _todo(CONSULTAR),
        "CATALOGOS": _todo(CONSULTAR),
        "VENTAS": _todo(CONSULTAR, OPERAR),
        "FINANZAS": _todo(CONSULTAR),
        "NOMINA": _todo(CONSULTAR),
        "REPORTES": _todo(EXPORTAR_PDF),
    },
    "SOPORTE_TECNICO": {
        "OPERACION": _todo(CONSULTAR),
    },
    "INTEGRACION_API": {},
}

# Acciones que comienzan desactivadas y requieren un permiso explícito en la
# asignación (matriz §2 "Condicionado"). Clave: (rol, módulo, acción) → permiso.
CONDICIONADAS: dict[tuple[str, str, str], str] = {
    ("CONSULTORA_CAPTURISTA", "REPORTES", EXPORTAR_CSV): "EXPORTAR_CSV",
    ("CLIENTE_RESPONSABLE", "REPORTES", EXPORTAR_CSV): "EXPORTAR_CSV",
    ("CLIENTE_FINANZAS", "REPORTES", EXPORTAR_CSV): "EXPORTAR_CSV",
    ("CLIENTE_RESPONSABLE", "VENTAS", OPERAR): "CAPTURAR_VENTAS",
    ("CLIENTE_FINANZAS", "COMPROBANTES", OPERAR): "OPERAR_COMPROBANTES",
    ("CLIENTE_FINANZAS", "COMPROBANTES", APROBAR): "OPERAR_COMPROBANTES",
    ("CLIENTE_FINANZAS", "FINANZAS", OPERAR): "MODIFICAR_PROVISIONES",
    ("CLIENTE_OPERADOR", "NOMINA", CONSULTAR): "CONSULTAR_NOMINA",
    ("CLIENTE_OPERADOR", "REPORTES", EXPORTAR_PDF): "GENERAR_PDF",
}


# Módulos que exigen sesión incluso en modo abierto: no existían antes del
# control de acceso y no tienen comportamiento anónimo que conservar.
MODULOS_SIEMPRE_CON_SESION = frozenset({"IDENTIDADES", "AUDITORIA", "CLIENTES", "OPERACION"})


@dataclass(frozen=True)
class ReglaRuta:
    modulo: str | None    # None = ruta pública o de sesión (sin datos de clientes)
    accion: str | None
    nivel: Nivel = Nivel.C0
    sucursal_param: str | None = None  # parámetro que trae la sucursal, si existe


PUBLICA = ReglaRuta(None, None)

_D, _C, _P, _K = "DOCUMENTOS", "COMPROBANTES", "PROVEEDORES", "CATALOGOS"
_V, _F, _R, _N = "VENTAS", "FINANZAS", "REPORTES", "NOMINA"

# (método, ruta) → regla. Fuente única de la clasificación de la API.
RUTAS: dict[tuple[str, str], ReglaRuta] = {
    ("GET", "/"): PUBLICA,
    ("GET", "/health"): PUBLICA,
    # Documentos y facturas
    ("POST", "/api/v1/facturas"): ReglaRuta(_D, OPERAR, Nivel.C0, "sucursal_clave"),
    ("POST", "/api/v1/documentos/carga-masiva"): ReglaRuta(_D, OPERAR, Nivel.C1, "sucursal_clave"),
    ("GET", "/api/v1/cola-ocr"): ReglaRuta(_D, CONSULTAR),
    ("GET", "/api/v1/duplicados"): ReglaRuta(_D, CONSULTAR),
    ("GET", "/api/v1/duplicados/{duplicado_id}/archivo"): ReglaRuta(_D, CONSULTAR, Nivel.C1),
    ("POST", "/api/v1/duplicados/descartar"): ReglaRuta(_D, ELIMINAR, Nivel.C1),
    ("POST", "/api/v1/facturas/{factura_id}/procesar-simulado"): ReglaRuta(_D, OPERAR),
    ("POST", "/api/v1/facturas/{factura_id}/procesar-ocr"): ReglaRuta(_D, OPERAR),
    ("GET", "/api/v1/revision/resumen"): ReglaRuta(_D, CONSULTAR, Nivel.C0, "sucursal_clave"),
    ("GET", "/api/v1/revision"): ReglaRuta(_D, CONSULTAR, Nivel.C0, "sucursal_clave"),
    ("GET", "/api/v1/facturas/{factura_id}"): ReglaRuta(_D, CONSULTAR),
    ("DELETE", "/api/v1/facturas"): ReglaRuta(_D, ELIMINAR, Nivel.C2),
    ("POST", "/api/v1/continuaciones/{vinculo_id}/separar"): ReglaRuta(_D, OPERAR),
    ("GET", "/api/v1/facturas/{factura_id}/expediente"): ReglaRuta(_D, CONSULTAR),
    ("GET", "/api/v1/facturas/{factura_id}/archivo"): ReglaRuta(_D, CONSULTAR, Nivel.C1),
    ("GET", "/api/v1/catalogos"): ReglaRuta(_K, CONSULTAR),
    ("GET", "/api/v1/documentos/buscar"): ReglaRuta(_D, CONSULTAR),
    ("GET", "/api/v1/documentos/archivo"): ReglaRuta(_D, CONSULTAR, Nivel.C0, "sucursal_clave"),
    ("POST", "/api/v1/lotes"): ReglaRuta(_D, OPERAR, Nivel.C1, "sucursal_clave"),
    ("GET", "/api/v1/lotes"): ReglaRuta(_D, CONSULTAR),
    ("POST", "/api/v1/lotes/{lote_id}/procesar"): ReglaRuta(_D, OPERAR),
    ("POST", "/api/v1/lotes/{lote_id}/cancelar"): ReglaRuta(_D, ELIMINAR, Nivel.C2),
    ("DELETE", "/api/v1/lotes/{lote_id}"): ReglaRuta(_D, ELIMINAR, Nivel.C2),
    ("POST", "/api/v1/lotes/{lote_id}/reprocesar"): ReglaRuta(_D, OPERAR),
    ("POST", "/api/v1/lotes/{lote_id}/reclasificar"): ReglaRuta(_D, OPERAR),
    ("POST", "/api/v1/facturas/{factura_id}/aprobar"): ReglaRuta(_D, APROBAR, Nivel.C1),
    ("POST", "/api/v1/facturas/{factura_id}/corregir"): ReglaRuta(_D, OPERAR),
    ("POST", "/api/v1/facturas/{factura_id}/editar"): ReglaRuta(_D, APROBAR, Nivel.C2),
    ("POST", "/api/v1/facturas/{factura_id}/rechazar"): ReglaRuta(_D, APROBAR, Nivel.C1),
    # Comprobantes internos
    ("POST", "/api/v1/comprobantes-internos"): ReglaRuta(_C, OPERAR, Nivel.C0, "sucursal_clave"),
    ("GET", "/api/v1/comprobantes-internos"): ReglaRuta(_C, CONSULTAR),
    ("GET", "/api/v1/comprobantes-internos/{receipt_id}"): ReglaRuta(_C, CONSULTAR),
    ("POST", "/api/v1/comprobantes-internos/{receipt_id}/aprobar"): ReglaRuta(_C, APROBAR, Nivel.C2),
    ("POST", "/api/v1/comprobantes-internos/{receipt_id}/rechazar"): ReglaRuta(_C, APROBAR, Nivel.C2),
    ("POST", "/api/v1/comprobantes-internos/{receipt_id}/sustituir"): ReglaRuta(_C, OPERAR, Nivel.C1),
    ("GET", "/api/v1/comprobantes-internos/{receipt_id}/pdf"): ReglaRuta(_C, EXPORTAR_PDF, Nivel.C1),
    ("GET", "/api/v1/comprobantes-internos/{receipt_id}/evidencia"): ReglaRuta(_C, CONSULTAR, Nivel.C1),
    # Proveedores y catálogos
    ("GET", "/api/v1/proveedores"): ReglaRuta(_P, CONSULTAR),
    ("GET", "/api/v1/proveedores/plantilla"): ReglaRuta(_P, CONSULTAR),
    ("POST", "/api/v1/proveedores"): ReglaRuta(_P, OPERAR, Nivel.C1),
    ("POST", "/api/v1/proveedores/importar"): ReglaRuta(_P, OPERAR, Nivel.C2),
    ("GET", "/api/v1/calidad-datos"): ReglaRuta(_P, CONSULTAR),
    ("GET", "/api/v1/entrenamiento/resumen"): ReglaRuta(_P, CONSULTAR),
    ("GET", "/api/v1/catalogos/contables"): ReglaRuta(_K, CONSULTAR),
    ("POST", "/api/v1/catalogos/subcategorias"): ReglaRuta(_K, ADMINISTRAR, Nivel.C2),
    ("GET", "/api/v1/entidades-propias"): ReglaRuta(_K, CONSULTAR),
    ("POST", "/api/v1/entidades-propias"): ReglaRuta(_K, ADMINISTRAR, Nivel.C2),
    ("GET", "/api/v1/gastos-fijos"): ReglaRuta(_F, CONSULTAR),
    ("POST", "/api/v1/gastos-fijos"): ReglaRuta(_F, OPERAR, Nivel.C2),
    # Nómina y comisiones
    ("GET", "/api/v1/finanzas/nomina"): ReglaRuta(_N, CONSULTAR, Nivel.C1, "sucursal_clave"),
    ("POST", "/api/v1/finanzas/nomina"): ReglaRuta(_N, OPERAR, Nivel.C2),
    ("GET", "/api/v1/finanzas/comisiones/parametros"): ReglaRuta(_F, CONSULTAR, Nivel.C0, "sucursal_clave"),
    ("POST", "/api/v1/finanzas/comisiones/parametros"): ReglaRuta(_F, OPERAR, Nivel.C2),
    ("DELETE", "/api/v1/finanzas/comisiones/parametros/{parameter_id}"): ReglaRuta(_F, OPERAR, Nivel.C2),
    ("GET", "/api/v1/finanzas/comisiones/mes"): ReglaRuta(_F, CONSULTAR, Nivel.C0, "sucursal_clave"),
    ("POST", "/api/v1/finanzas/comisiones/cierre"): ReglaRuta(_F, OPERAR, Nivel.C2),
    # Analytics, finanzas y reportes
    ("GET", "/api/v1/analytics/resumen"): ReglaRuta(_F, CONSULTAR),
    ("GET", "/api/v1/analytics/dashboard"): ReglaRuta(_F, CONSULTAR, Nivel.C0, "sucursal_clave"),
    ("GET", "/api/v1/analytics/exportar.csv"): ReglaRuta(_R, EXPORTAR_CSV, Nivel.C3, "sucursal_clave"),
    ("GET", "/api/v1/finanzas/estado-resultados"): ReglaRuta(_F, CONSULTAR, Nivel.C0, "sucursal_clave"),
    ("GET", "/api/v1/finanzas/reporte-compras.pdf"): ReglaRuta(_R, EXPORTAR_PDF, Nivel.C1, "sucursal_clave"),
    ("GET", "/api/v1/finanzas/reporte-ejecutivo.pdf"): ReglaRuta(_R, EXPORTAR_PDF, Nivel.C1, "sucursal_clave"),
    ("GET", "/api/v1/finanzas/reporte-ejecutivo-vacio.pdf"): ReglaRuta(_R, EXPORTAR_PDF, Nivel.C1, "sucursal_clave"),
    ("GET", "/api/v1/reportes-financieros/opciones"): ReglaRuta(_R, CONSULTAR),
    ("GET", "/api/v1/reportes-financieros/resumen"): ReglaRuta(_R, CONSULTAR, Nivel.C0, "sucursal_clave"),
    ("GET", "/api/v1/reportes-financieros/reporte.pdf"): ReglaRuta(_R, EXPORTAR_PDF, Nivel.C1, "sucursal_clave"),
    # Ventas
    ("POST", "/api/v1/finanzas/ventas"): ReglaRuta(_V, OPERAR, Nivel.C0, "sucursal_clave"),
    ("GET", "/api/v1/finanzas/ventas-desglose"): ReglaRuta(_V, CONSULTAR, Nivel.C0, "sucursal_clave"),
    ("POST", "/api/v1/finanzas/ventas-desglose"): ReglaRuta(_V, OPERAR),
    ("POST", "/api/v1/finanzas/ventas-desglose/archivo"): ReglaRuta(_V, OPERAR, Nivel.C0, "sucursal_clave"),
    ("POST", "/api/v1/finanzas/ventas-desglose/imagen"): ReglaRuta(_V, OPERAR, Nivel.C0, "sucursal_clave"),
    # Acceso y seguridad. Las rutas de sesión hacen su propia comprobación.
    ("GET", "/auth/entrar"): PUBLICA,
    ("GET", "/auth/reautenticar"): PUBLICA,
    ("GET", "/auth/callback"): PUBLICA,
    ("POST", "/auth/salir"): PUBLICA,
    ("GET", "/auth/salida"): PUBLICA,
    ("GET", "/api/v1/seguridad/sesion"): PUBLICA,
    ("POST", "/api/v1/seguridad/contexto"): PUBLICA,
    ("GET", "/api/v1/seguridad/mi-actividad"): PUBLICA,
    ("GET", "/api/v1/seguridad/identidades"): ReglaRuta("IDENTIDADES", CONSULTAR, Nivel.C1),
    ("POST", "/api/v1/seguridad/invitaciones"): ReglaRuta("IDENTIDADES", ADMINISTRAR, Nivel.C2),
    ("POST", "/api/v1/seguridad/identidades/{identidad_id}/suspender"): ReglaRuta("IDENTIDADES", ADMINISTRAR, Nivel.C2),
    ("POST", "/api/v1/seguridad/identidades/{identidad_id}/revocar-sesiones"): ReglaRuta("IDENTIDADES", ADMINISTRAR, Nivel.C2),
    ("GET", "/api/v1/seguridad/auditoria"): ReglaRuta("AUDITORIA", CONSULTAR, Nivel.C1),
    # Ciclo de vida (fase 6). Las reglas finas (no a sí mismo, roles globales, C3) viven en ciclo_vida.py.
    ("GET", "/auth/registrar-autenticador"): PUBLICA,
    ("GET", "/api/v1/seguridad/mi-cuenta"): PUBLICA,
    ("POST", "/api/v1/seguridad/mi-cuenta/autenticadores/{credencial_id}/perdido"): PUBLICA,
    ("GET", "/api/v1/seguridad/identidades/{identidad_id}"): ReglaRuta("IDENTIDADES", CONSULTAR, Nivel.C1),
    ("POST", "/api/v1/seguridad/identidades/{identidad_id}/asignaciones"): ReglaRuta("IDENTIDADES", ADMINISTRAR, Nivel.C2),
    ("PUT", "/api/v1/seguridad/asignaciones/{asignacion_id}"): ReglaRuta("IDENTIDADES", ADMINISTRAR, Nivel.C2),
    ("POST", "/api/v1/seguridad/asignaciones/{asignacion_id}/revocar"): ReglaRuta("IDENTIDADES", ADMINISTRAR, Nivel.C2),
    ("POST", "/api/v1/seguridad/identidades/{identidad_id}/reactivar"): ReglaRuta("IDENTIDADES", ADMINISTRAR, Nivel.C2),
    ("POST", "/api/v1/seguridad/identidades/{identidad_id}/baja"): ReglaRuta("IDENTIDADES", ADMINISTRAR, Nivel.C2),
    ("POST", "/api/v1/seguridad/identidades/{identidad_id}/reingreso"): ReglaRuta("IDENTIDADES", ADMINISTRAR, Nivel.C2),
    ("POST", "/api/v1/seguridad/identidades/{identidad_id}/autenticadores/{credencial_id}/perdido"):
        ReglaRuta("IDENTIDADES", ADMINISTRAR, Nivel.C2),
    ("POST", "/api/v1/seguridad/identidades/{identidad_id}/recuperacion"): ReglaRuta("IDENTIDADES", ADMINISTRAR, Nivel.C2),
    ("POST", "/api/v1/seguridad/recuperaciones/{recuperacion_id}/ejecutar"): ReglaRuta("IDENTIDADES", ADMINISTRAR, Nivel.C2),
    ("POST", "/api/v1/seguridad/recuperaciones/{recuperacion_id}/cancelar"): ReglaRuta("IDENTIDADES", ADMINISTRAR, Nivel.C2),
}


def permitido(rol: str, modulo: str, accion: str, *, modulos_asignados: list[str] | None, condicionados: list[str]) -> bool:
    """¿Permite la asignación esta acción? Deniega por defecto."""
    if accion not in MATRIZ.get(rol, {}).get(modulo, frozenset()):
        return False
    if modulos_asignados is not None and modulo not in modulos_asignados:
        return False
    requerido = CONDICIONADAS.get((rol, modulo, accion))
    return requerido is None or requerido in condicionados


def modulos_visibles(rol: str, modulos_asignados: list[str] | None) -> list[str]:
    del_rol = [m for m, acciones in MATRIZ.get(rol, {}).items() if acciones]
    return [m for m in del_rol if modulos_asignados is None or m in modulos_asignados]
