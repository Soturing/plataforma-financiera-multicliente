from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.security.data_plane import DataPlaneAccess


class BranchBinding(str, Enum):
    TENANT_WIDE = "tenant_wide"
    REQUEST_FORM = "request_form"
    REQUEST_QUERY = "request_query"
    REQUEST_BODY = "request_body"
    RESOURCE_LOOKUP = "resource_lookup"
    MULTI_RESOURCE_LOOKUP = "multi_resource_lookup"
    RLS_COLLECTION = "rls_collection"


@dataclass(frozen=True)
class BusinessRoutePolicy:
    actions: tuple[str, ...]
    access: DataPlaneAccess
    branch_binding: BranchBinding
    untrusted_actor_fields: tuple[str, ...] = ()


def _policy(
    action: str,
    access: DataPlaneAccess,
    branch_binding: BranchBinding,
    *,
    actor_fields: tuple[str, ...] = (),
    additional_actions: tuple[str, ...] = (),
) -> BusinessRoutePolicy:
    return BusinessRoutePolicy(
        actions=(action, *additional_actions),
        access=access,
        branch_binding=branch_binding,
        untrusted_actor_fields=actor_fields,
    )


R = DataPlaneAccess.READ
W = DataPlaneAccess.WRITE
TENANT = BranchBinding.TENANT_WIDE
FORM = BranchBinding.REQUEST_FORM
QUERY = BranchBinding.REQUEST_QUERY
BODY = BranchBinding.REQUEST_BODY
RESOURCE = BranchBinding.RESOURCE_LOOKUP
MULTI = BranchBinding.MULTI_RESOURCE_LOOKUP
COLLECTION = BranchBinding.RLS_COLLECTION


# This catalog is intentionally explicit. An unlisted business route must fail
# the coverage test and cannot be enabled in secure mode by default.
BUSINESS_ROUTE_POLICIES: dict[tuple[str, str], BusinessRoutePolicy] = {
    ("POST", "/api/v1/facturas"): _policy("documents.upload", W, FORM, actor_fields=("creada_por",)),
    ("POST", "/api/v1/documentos/carga-masiva"): _policy(
        "documents.bulk_upload", W, FORM, actor_fields=("creada_por",)
    ),
    ("GET", "/api/v1/duplicados"): _policy("documents.duplicates.read", R, COLLECTION),
    ("GET", "/api/v1/duplicados/{duplicado_id}/archivo"): _policy(
        "documents.original.read", R, RESOURCE
    ),
    ("POST", "/api/v1/duplicados/descartar"): _policy(
        "documents.duplicates.discard", W, MULTI, actor_fields=("descartado_por",)
    ),
    ("POST", "/api/v1/facturas/{factura_id}/procesar-simulado"): _policy(
        "documents.reprocess", W, RESOURCE
    ),
    ("POST", "/api/v1/facturas/{factura_id}/procesar-ocr"): _policy(
        "documents.reprocess", W, RESOURCE
    ),
    ("GET", "/api/v1/revision/resumen"): _policy("documents.review", R, QUERY),
    ("GET", "/api/v1/revision"): _policy("documents.review", R, QUERY),
    ("GET", "/api/v1/facturas/{factura_id}"): _policy("documents.read", R, RESOURCE),
    ("DELETE", "/api/v1/facturas"): _policy(
        "documents.delete_pending", W, MULTI, actor_fields=("eliminado_por",)
    ),
    ("GET", "/api/v1/facturas/{factura_id}/expediente"): _policy(
        "documents.read", R, RESOURCE
    ),
    ("GET", "/api/v1/facturas/{factura_id}/archivo"): _policy(
        "documents.original.read", R, RESOURCE
    ),
    ("GET", "/api/v1/catalogos"): _policy(
        "providers.read", R, TENANT, additional_actions=("accounting_catalogs.read",)
    ),
    ("GET", "/api/v1/documentos/buscar"): _policy("documents.read", R, COLLECTION),
    ("GET", "/api/v1/documentos/archivo"): _policy("documents.read", R, QUERY),
    ("POST", "/api/v1/comprobantes-internos"): _policy(
        "receipts.create",
        W,
        FORM,
        actor_fields=("creado_por", "rol_creador"),
    ),
    ("GET", "/api/v1/comprobantes-internos"): _policy("receipts.read", R, COLLECTION),
    ("GET", "/api/v1/comprobantes-internos/{receipt_id}"): _policy(
        "receipts.read", R, RESOURCE
    ),
    ("POST", "/api/v1/comprobantes-internos/{receipt_id}/aprobar"): _policy(
        "receipts.approve", W, RESOURCE, actor_fields=("autorizada_por",)
    ),
    ("POST", "/api/v1/comprobantes-internos/{receipt_id}/rechazar"): _policy(
        "receipts.approve", W, RESOURCE, actor_fields=("rechazada_por",)
    ),
    ("POST", "/api/v1/comprobantes-internos/{receipt_id}/sustituir"): _policy(
        "receipts.replace", W, RESOURCE
    ),
    ("GET", "/api/v1/comprobantes-internos/{receipt_id}/pdf"): _policy(
        "receipts.download", R, RESOURCE
    ),
    ("GET", "/api/v1/comprobantes-internos/{receipt_id}/evidencia"): _policy(
        "receipts.download", R, RESOURCE
    ),
    ("GET", "/api/v1/proveedores"): _policy("providers.read", R, TENANT),
    ("GET", "/api/v1/proveedores/plantilla"): _policy("providers.read", R, TENANT),
    ("POST", "/api/v1/proveedores"): _policy(
        "providers.write", W, TENANT, actor_fields=("actualizado_por",)
    ),
    ("GET", "/api/v1/calidad-datos"): _policy("providers.learning.read", R, TENANT),
    ("GET", "/api/v1/catalogos/contables"): _policy("accounting_catalogs.read", R, TENANT),
    ("POST", "/api/v1/catalogos/subcategorias"): _policy(
        "accounting_catalogs.write", W, TENANT, actor_fields=("actualizado_por",)
    ),
    ("POST", "/api/v1/catalogos/centros-costo"): _policy(
        "accounting_catalogs.write", W, TENANT, actor_fields=("actualizado_por",)
    ),
    ("GET", "/api/v1/entrenamiento/resumen"): _policy(
        "providers.learning.read", R, TENANT
    ),
    ("POST", "/api/v1/proveedores/importar"): _policy(
        "providers.import", W, TENANT, actor_fields=("importado_por",)
    ),
    ("GET", "/api/v1/analytics/resumen"): _policy("finance.read", R, COLLECTION),
    ("GET", "/api/v1/analytics/dashboard"): _policy("finance.read", R, QUERY),
    ("GET", "/api/v1/analytics/exportar.csv"): _policy("reports.csv_export", R, QUERY),
    ("GET", "/api/v1/finanzas/estado-resultados"): _policy("finance.read", R, QUERY),
    ("GET", "/api/v1/finanzas/reporte-compras.pdf"): _policy("reports.pdf", R, QUERY),
    ("GET", "/api/v1/finanzas/reporte-ejecutivo.pdf"): _policy("reports.pdf", R, QUERY),
    ("GET", "/api/v1/finanzas/reporte-ejecutivo-vacio.pdf"): _policy(
        "reports.pdf", R, QUERY
    ),
    ("GET", "/api/v1/reportes-financieros/opciones"): _policy("reports.pdf", R, TENANT),
    ("GET", "/api/v1/reportes-financieros/resumen"): _policy("reports.pdf", R, QUERY),
    ("GET", "/api/v1/reportes-financieros/reporte.pdf"): _policy("reports.pdf", R, QUERY),
    ("POST", "/api/v1/finanzas/ventas"): _policy(
        "sales.write", W, BODY, actor_fields=("registrada_por",)
    ),
    ("GET", "/api/v1/finanzas/ventas-desglose"): _policy("sales.read", R, QUERY),
    ("POST", "/api/v1/finanzas/ventas-desglose"): _policy(
        "sales.write", W, BODY, actor_fields=("actualizada_por",)
    ),
    ("POST", "/api/v1/finanzas/ventas-desglose/archivo"): _policy("sales.write", W, FORM),
    ("POST", "/api/v1/finanzas/ventas-desglose/imagen"): _policy("sales.write", W, FORM),
    ("POST", "/api/v1/lotes"): _policy(
        "documents.bulk_upload", W, FORM, actor_fields=("creada_por",)
    ),
    ("GET", "/api/v1/lotes"): _policy("documents.read", R, COLLECTION),
    ("POST", "/api/v1/lotes/{lote_id}/procesar"): _policy(
        "documents.reprocess", W, RESOURCE
    ),
    ("POST", "/api/v1/lotes/{lote_id}/cancelar"): _policy(
        "documents.cancel_batch", W, RESOURCE, actor_fields=("cancelado_por",)
    ),
    ("DELETE", "/api/v1/lotes/{lote_id}"): _policy(
        "documents.cancel_batch", W, RESOURCE, actor_fields=("eliminado_por",)
    ),
    ("POST", "/api/v1/lotes/{lote_id}/reprocesar"): _policy(
        "documents.reprocess", W, RESOURCE
    ),
    ("POST", "/api/v1/lotes/{lote_id}/reclasificar"): _policy(
        "documents.reprocess", W, RESOURCE
    ),
    ("POST", "/api/v1/facturas/{factura_id}/aprobar"): _policy(
        "documents.approve", W, RESOURCE, actor_fields=("revisada_por",)
    ),
    ("POST", "/api/v1/facturas/{factura_id}/corregir"): _policy(
        "documents.approve", W, RESOURCE, actor_fields=("revisada_por",)
    ),
    ("POST", "/api/v1/facturas/{factura_id}/editar"): _policy(
        "documents.edit_approved", W, RESOURCE, actor_fields=("revisada_por",)
    ),
    ("POST", "/api/v1/facturas/{factura_id}/rechazar"): _policy(
        "documents.approve", W, RESOURCE, actor_fields=("revisada_por",)
    ),
}
