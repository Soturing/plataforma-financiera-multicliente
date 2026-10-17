import csv
import io
import re
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from psycopg import Connection

from app.config import Settings, get_settings
from app.database import get_connection
from app.errors import DomainError
from app.weekly_report import build_weekly_purchase_report
from app.executive_report import build_blank_executive_report, build_weekly_executive_report
from app.financial_reports import (
    build_configurable_financial_report,
    build_report_summary,
    get_report_options,
)
from app.accounting import (
    get_weekly_statement,
    get_sales_breakdown,
    list_accounting_catalogs,
    register_sale,
    save_subcategory,
    save_sales_breakdown,
)
from app.repository import (
    cancel_batch,
    create_batch,
    create_invoice,
    delete_pending_invoices,
    discard_document_duplicates,
    find_invoice_by_sha256,
    decide_invoice,
    edit_approved_invoice,
    get_invoice,
    get_invoice_case,
    get_review_queue_summary,
    get_analytics_dashboard,
    get_analytics_export_rows,
    get_analytics_summary,
    list_catalogs,
    list_batches,
    list_document_duplicates,
    list_review_queue,
    process_simulated,
    register_hash_duplicate,
    browse_documents,
    search_documents,
)
from app.schemas import (
    AprobarComprobanteRequest,
    AprobarRequest,
    CorregirRequest,
    EditarFacturaRequest,
    DecisionResultado,
    FacturaCreada,
    FacturaRevision,
    HealthResponse,
    LoteCreado,
    LoteResumen,
    ProcesamientoResultado,
    ProcesamientoSimulado,
    ProveedorCatalogoRequest,
    SubcategoriaCatalogoRequest,
    GastoFijoRequest,
    EliminarDocumentosRequest,
    EliminarLoteRequest,
    CancelarLoteRequest,
    DescartarDuplicadosRequest,
    VentaManualRequest,
    VentasDesgloseRequest,
    RechazarRequest,
    RechazarComprobanteRequest,
    SustituirComprobanteRequest,
)
from app.storage import save_upload
from app.ocr.paddle_engine import get_ocr_engine
from app.sales_image import parse_sales_image
from app.sales_xlsx import parse_sales_xlsx
from app.periodification import parse_periodification
from app.receipt_pdf import render_receipt_pdf
from app.receipts import (
    approve_internal_receipt,
    create_internal_receipt,
    evidence_path,
    get_internal_receipt,
    list_internal_receipts,
    parse_distributions,
    reject_internal_receipt,
    replace_internal_receipt,
)
from app.pdf_splitter import pdf_page_count, split_pdf
from uuid import uuid4
import shutil
from app.jobs import is_batch_active, start_batch_job, start_invoice_job
from app.classification import reclassify_batch
from app.provider_template import build_provider_template
from app.fixed_expenses import list_fixed_expenses, save_fixed_expense
from app.provider_catalog import (
    apply_provider_import,
    list_providers,
    parse_provider_file,
    preview_provider_import,
    provider_quality,
    save_provider,
    training_summary,
)


app = FastAPI(
    title="Facturación IA API",
    version="0.1.0",
    description="Backend auditable para la demo de procesamiento de facturas.",
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def prevent_stale_demo_assets(request, call_next):
    response = await call_next(request)
    if (
        request.url.path == "/"
        or request.url.path.startswith("/static/")
        or request.url.path.startswith("/api/")
    ):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(DomainError)
async def domain_error_handler(_, exc: DomainError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.get("/", include_in_schema=False)
def user_interface():
    return FileResponse("app/static/index.html")


@app.get("/health", response_model=HealthResponse, tags=["sistema"])
def health(conn: Connection = Depends(get_connection)):
    conn.execute("SELECT 1").fetchone()
    return {"status": "ok", "database": "ok"}


@app.post("/api/v1/facturas", response_model=FacturaCreada, status_code=201, tags=["facturas"])
async def upload_invoice(
    archivo: UploadFile = File(...),
    sucursal_clave: str = Form(...),
    creada_por: str = Form(...),
    permitir_pdf_multipagina: bool = Form(default=False),
    conn: Connection = Depends(get_connection),
    settings: Settings = Depends(get_settings),
):
    path, digest, _ = await save_upload(archivo, settings)
    try:
        if path.suffix.lower() == ".pdf" and not permitir_pdf_multipagina:
            pages = pdf_page_count(path)
            if pages > 1:
                raise DomainError(
                    f"El PDF contiene {pages} páginas. Cárguelo como lote para crear un documento por página.",
                    409,
                )
        return create_invoice(
            conn,
            sucursal_clave=sucursal_clave,
            filename=archivo.filename or path.name,
            mime="application/xml" if path.suffix.lower() == ".xml" else (archivo.content_type or "application/octet-stream"),
            file_path=str(path.resolve()),
            sha256=digest,
            created_by=creada_por,
        )
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise


@app.post("/api/v1/documentos/carga-masiva", status_code=201, tags=["facturas"])
async def upload_documents(
    archivos: list[UploadFile] = File(...),
    sucursal_clave: str = Form(...),
    creada_por: str = Form(...),
    conn: Connection = Depends(get_connection),
    settings: Settings = Depends(get_settings),
):
    if not archivos or len(archivos) > 100:
        raise DomainError("Selecciona entre 1 y 100 documentos.", 422)

    created = []
    duplicates = []
    errors = []
    for archivo in archivos:
        path = None
        try:
            path, digest, _ = await save_upload(archivo, settings)
            if path.suffix.lower() == ".pdf" and pdf_page_count(path) > 1:
                raise DomainError(
                    "El PDF contiene varias páginas. Cárguelo individualmente para separarlo automáticamente.",
                    422,
                )
            existing = find_invoice_by_sha256(conn, digest)
            if existing:
                duplicate = register_hash_duplicate(
                    conn,
                    original_invoice_id=existing["id"],
                    filename=archivo.filename or path.name,
                    file_path=str(path.resolve()),
                    sha256=digest,
                )
                duplicates.append({
                    **duplicate,
                    "archivo_original": existing["archivo_nombre"],
                    "estado_original": existing["estado"],
                })
                continue
            row = create_invoice(
                conn,
                sucursal_clave=sucursal_clave,
                filename=archivo.filename or path.name,
                mime="application/xml" if path.suffix.lower() == ".xml" else (archivo.content_type or "application/octet-stream"),
                file_path=str(path.resolve()),
                sha256=digest,
                created_by=creada_por,
            )
            created.append({**row, "archivo_url": str(path.resolve())})
        except DomainError as exc:
            if path:
                Path(path).unlink(missing_ok=True)
            target = duplicates if exc.status_code == 409 else errors
            target.append({"archivo": archivo.filename, "detalle": exc.message})

    conn.commit()
    for item in created:
        start_invoice_job(item["id"], item.pop("archivo_url"))

    return {
        "creados": created,
        "duplicados": duplicates,
        "errores": errors,
        "procesamiento_iniciado": len(created),
    }


@app.get("/api/v1/duplicados", tags=["facturas"])
def document_duplicates(conn: Connection = Depends(get_connection)):
    return list_document_duplicates(conn)


@app.get("/api/v1/duplicados/{duplicado_id}/archivo", tags=["facturas"])
def duplicate_file(
    duplicado_id: UUID,
    conn: Connection = Depends(get_connection),
    settings: Settings = Depends(get_settings),
):
    row = conn.execute(
        """
        SELECT archivo_url, archivo_nombre
        FROM core.documentos_duplicados
        WHERE id = %s AND estado = 'pendiente'
        """,
        (duplicado_id,),
    ).fetchone()
    if not row:
        raise DomainError("Duplicado no encontrado.", 404)
    path = Path(row["archivo_url"]).resolve()
    upload_root = settings.upload_dir.resolve()
    if not path.is_relative_to(upload_root) or not path.is_file():
        raise DomainError("El archivo duplicado no está disponible.", 404)
    media_types = {
        ".pdf": "application/pdf",
        ".xml": "application/xml",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    return FileResponse(
        path,
        media_type=media_types.get(path.suffix.lower(), "application/octet-stream"),
        filename=row["archivo_nombre"],
        content_disposition_type="inline",
    )


@app.post("/api/v1/duplicados/descartar", tags=["facturas"])
def discard_duplicates(
    data: DescartarDuplicadosRequest,
    conn: Connection = Depends(get_connection),
    settings: Settings = Depends(get_settings),
):
    rows = discard_document_duplicates(conn, data.duplicado_ids, data.descartado_por)
    conn.commit()
    upload_root = settings.upload_dir.resolve()
    removed_files = 0
    for row in rows:
        path = Path(row["archivo_url"]).resolve()
        if path.is_relative_to(upload_root) and path.is_file():
            path.unlink()
            removed_files += 1
    return {"descartados": len(rows), "archivos_eliminados": removed_files}


@app.post(
    "/api/v1/facturas/{factura_id}/procesar-simulado",
    response_model=ProcesamientoResultado,
    tags=["procesamiento"],
)
def simulate_processing(
    factura_id: UUID,
    data: ProcesamientoSimulado,
    conn: Connection = Depends(get_connection),
):
    return process_simulated(conn, factura_id, data)


@app.post("/api/v1/facturas/{factura_id}/procesar-ocr", status_code=202, tags=["procesamiento"])
def process_real_ocr(factura_id: UUID, conn: Connection = Depends(get_connection)):
    row = conn.execute(
        "SELECT estado::text, archivo_url FROM core.facturas WHERE id = %s",
        (factura_id,),
    ).fetchone()
    if not row:
        raise DomainError("Factura no encontrada.", 404)
    if row["estado"] not in {"recibida", "error"}:
        raise DomainError(f"La factura no puede procesarse desde {row['estado']}.", 409)
    started = start_invoice_job(factura_id, row["archivo_url"])
    return {"factura_id": factura_id, "estado": "procesando", "iniciado": started}


@app.get("/api/v1/revision/resumen", tags=["revision"])
def review_queue_summary(
    tipo_documento: str | None = Query(default=None, max_length=40),
    proveedor: str | None = Query(default=None, max_length=120),
    sucursal_clave: str | None = Query(default=None, max_length=40),
    conn: Connection = Depends(get_connection),
):
    return get_review_queue_summary(
        conn,
        document_type=tipo_documento,
        provider=proveedor,
        branch_key=sucursal_clave,
    )


@app.get("/api/v1/revision", response_model=list[FacturaRevision], tags=["revision"])
def review_queue(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tipo_documento: str | None = Query(default=None, max_length=40),
    proveedor: str | None = Query(default=None, max_length=120),
    sucursal_clave: str | None = Query(default=None, max_length=40),
    orden: Literal[
        "prioridad", "recientes", "antiguas", "proveedor_az",
        "proveedor_za", "total_mayor", "total_menor",
    ] = Query(default="prioridad"),
    conn: Connection = Depends(get_connection),
):
    return list_review_queue(
        conn,
        limit,
        offset,
        document_type=tipo_documento,
        provider=proveedor,
        branch_key=sucursal_clave,
        order=orden,
    )


@app.get("/api/v1/facturas/{factura_id}", response_model=FacturaRevision, tags=["facturas"])
def invoice_detail(factura_id: UUID, conn: Connection = Depends(get_connection)):
    return get_invoice(conn, factura_id)


@app.delete("/api/v1/facturas", tags=["facturas"])
def delete_invoices(
    data: EliminarDocumentosRequest,
    conn: Connection = Depends(get_connection),
    settings: Settings = Depends(get_settings),
):
    result = delete_pending_invoices(conn, data.factura_ids, data.eliminado_por)
    conn.commit()
    upload_root = settings.upload_dir.resolve()
    removed_files = 0
    removed_paths = result.pop("archivos") + result.pop("lotes_eliminados")
    parent_dirs: set[Path] = set()
    for raw_path in removed_paths:
        path = Path(raw_path).resolve()
        if path.is_relative_to(upload_root) and path.is_file():
            parent_dirs.add(path.parent)
            path.unlink()
            removed_files += 1
    for directory in sorted(parent_dirs, key=lambda item: len(item.parts), reverse=True):
        if directory != upload_root and directory.is_relative_to(upload_root):
            try:
                directory.rmdir()
            except OSError:
                pass
    return {**result, "archivos_eliminados": removed_files}


@app.get("/api/v1/facturas/{factura_id}/expediente", tags=["facturas"])
def invoice_case(factura_id: UUID, conn: Connection = Depends(get_connection)):
    return get_invoice_case(conn, factura_id)


@app.get("/api/v1/facturas/{factura_id}/archivo", tags=["facturas"])
def invoice_file(
    factura_id: UUID,
    conn: Connection = Depends(get_connection),
    settings: Settings = Depends(get_settings),
):
    row = conn.execute(
        "SELECT archivo_url, archivo_nombre, archivo_mime FROM core.facturas WHERE id = %s",
        (factura_id,),
    ).fetchone()
    if not row:
        raise DomainError("Factura no encontrada.", 404)
    path = Path(row["archivo_url"]).resolve()
    upload_root = settings.upload_dir.resolve()
    if not path.is_relative_to(upload_root) or not path.is_file():
        raise DomainError("El archivo de la factura no está disponible.", 404)
    return FileResponse(
        path,
        media_type=row["archivo_mime"],
        filename=row["archivo_nombre"],
        content_disposition_type="inline",
    )


@app.get("/api/v1/catalogos", tags=["catalogos"])
def catalogs(conn: Connection = Depends(get_connection)):
    return list_catalogs(conn)


@app.get("/api/v1/documentos/buscar", tags=["documentos"])
def find_documents(
    numero: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    conn: Connection = Depends(get_connection),
):
    return search_documents(conn, numero, limit)


@app.get("/api/v1/documentos/archivo", tags=["documentos"])
def document_archive(
    q: str | None = Query(default=None, max_length=150),
    estado: str = Query(default="aprobada", pattern="^(aprobada|requiere_revision|rechazada|todos)$"),
    sucursal_clave: str | None = Query(default=None),
    fecha_desde: date | None = Query(default=None),
    fecha_hasta: date | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    conn: Connection = Depends(get_connection),
):
    if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
        raise DomainError("La fecha inicial no puede ser posterior a la fecha final.", 422)
    return browse_documents(
        conn,
        query=q,
        estado=estado,
        sucursal_clave=sucursal_clave,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        limit=limit,
    )


@app.post("/api/v1/comprobantes-internos", status_code=201, tags=["comprobantes internos"])
async def create_receipt(
    sucursal_clave: str = Form(...),
    proveedor_nombre: str = Form(...),
    numero_documento: str | None = Form(default=None),
    fecha_gasto: date = Form(...),
    concepto: str = Form(...),
    metodo_pago: str = Form(...),
    total: Decimal = Form(...),
    categoria_id: UUID = Form(...),
    creado_por: str = Form(...),
    rol_creador: str = Form(...),
    proveedor_telefono: str | None = Form(default=None),
    proveedor_giro: str | None = Form(default=None),
    subcategoria_id: UUID | None = Form(default=None),
    firma_proveedor_nombre: str | None = Form(default=None),
    firma_proveedor_confirmada: bool = Form(default=False),
    distribuciones: str | None = Form(default=None),
    periodificacion: str | None = Form(default=None),
    recordar_periodificacion: bool = Form(default=False),
    evidencia: UploadFile | None = File(default=None),
    conn: Connection = Depends(get_connection),
    settings: Settings = Depends(get_settings),
):
    saved_path = None
    evidence = None
    try:
        if evidencia and evidencia.filename:
            saved_path, digest, _ = await save_upload(evidencia, settings)
            evidence = {
                "path": str(saved_path.resolve()),
                "name": evidencia.filename,
                "mime": evidencia.content_type or "application/octet-stream",
                "sha256": digest,
            }
        return create_internal_receipt(
            conn,
            sucursal_clave=sucursal_clave,
            proveedor_nombre=proveedor_nombre,
            numero_documento=numero_documento,
            proveedor_telefono=proveedor_telefono,
            proveedor_giro=proveedor_giro,
            fecha_gasto=fecha_gasto,
            concepto=concepto,
            metodo_pago=metodo_pago,
            total=total,
            categoria_id=categoria_id,
            subcategoria_id=subcategoria_id,
            creado_por=creado_por,
            rol_creador=rol_creador,
            firma_proveedor_nombre=firma_proveedor_nombre,
            firma_proveedor_confirmada=firma_proveedor_confirmada,
            distribuciones=parse_distributions(distribuciones),
            evidencia=evidence,
            periodificacion=parse_periodification(periodificacion),
            recordar_periodificacion=recordar_periodificacion,
        )
    except Exception:
        if saved_path:
            saved_path.unlink(missing_ok=True)
        raise


@app.get("/api/v1/comprobantes-internos", tags=["comprobantes internos"])
def receipts(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    estado: str | None = Query(default=None),
    conn: Connection = Depends(get_connection),
):
    return list_internal_receipts(conn, limit=limit, offset=offset, state=estado)


@app.get("/api/v1/comprobantes-internos/{receipt_id}", tags=["comprobantes internos"])
def receipt_detail(receipt_id: UUID, conn: Connection = Depends(get_connection)):
    return get_internal_receipt(conn, receipt_id)


@app.post("/api/v1/comprobantes-internos/{receipt_id}/aprobar", tags=["comprobantes internos"])
def approve_receipt(
    receipt_id: UUID,
    data: AprobarComprobanteRequest,
    conn: Connection = Depends(get_connection),
):
    return approve_internal_receipt(
        conn, receipt_id, actor=data.autorizada_por, comment=data.comentario
    )


@app.post("/api/v1/comprobantes-internos/{receipt_id}/rechazar", tags=["comprobantes internos"])
def reject_receipt(
    receipt_id: UUID,
    data: RechazarComprobanteRequest,
    conn: Connection = Depends(get_connection),
):
    return reject_internal_receipt(
        conn, receipt_id, actor=data.rechazada_por, reason=data.motivo
    )


@app.post("/api/v1/comprobantes-internos/{receipt_id}/sustituir", tags=["comprobantes internos"])
def replace_receipt(
    receipt_id: UUID,
    data: SustituirComprobanteRequest,
    conn: Connection = Depends(get_connection),
):
    return replace_internal_receipt(conn, receipt_id, invoice_final_id=data.factura_final_id)


@app.get("/api/v1/comprobantes-internos/{receipt_id}/pdf", tags=["comprobantes internos"])
def receipt_pdf(receipt_id: UUID, conn: Connection = Depends(get_connection)):
    receipt = get_internal_receipt(conn, receipt_id)
    safe_number = re.sub(r"[^A-Za-z0-9._-]+", "-", receipt["numero_documento"]).strip("-")
    return Response(
        content=render_receipt_pdf(receipt),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="Comprobante-{safe_number or receipt["folio"]}.pdf"'},
    )


@app.get("/api/v1/comprobantes-internos/{receipt_id}/evidencia", tags=["comprobantes internos"])
def receipt_evidence(
    receipt_id: UUID,
    conn: Connection = Depends(get_connection),
    settings: Settings = Depends(get_settings),
):
    path, name, mime = evidence_path(conn, receipt_id)
    path = path.resolve()
    if not path.is_relative_to(settings.upload_dir.resolve()) or not path.is_file():
        raise DomainError("La evidencia no está disponible.", 404)
    return FileResponse(path, media_type=mime, filename=name, content_disposition_type="inline")


@app.get("/api/v1/proveedores", tags=["catalogos"])
def providers_catalog(conn: Connection = Depends(get_connection)):
    return list_providers(conn)


@app.get("/api/v1/proveedores/plantilla", tags=["catalogos"])
def provider_catalog_template(conn: Connection = Depends(get_connection)):
    categories = conn.execute(
        "SELECT clave, nombre FROM catalog.categorias WHERE activa AND admite_facturas ORDER BY orden"
    ).fetchall()
    subcategories = conn.execute(
        """
        SELECT c.clave AS categoria, sc.clave, sc.nombre
        FROM catalog.subcategorias sc JOIN catalog.categorias c ON c.id = sc.categoria_id
        WHERE sc.activa AND c.activa AND c.admite_facturas ORDER BY c.orden, sc.nombre
        """
    ).fetchall()
    return Response(
        build_provider_template(
            [(row["clave"], row["nombre"]) for row in categories],
            [(row["categoria"], row["clave"], row["nombre"]) for row in subcategories],
        ),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="Plantilla-catalogo-proveedores.xlsx"'},
    )


@app.post("/api/v1/proveedores", tags=["catalogos"])
def upsert_provider(
    data: ProveedorCatalogoRequest,
    conn: Connection = Depends(get_connection),
):
    payload = data.model_dump(mode="python")
    actor = payload.pop("actualizado_por")
    return save_provider(conn, payload, actor)


@app.get("/api/v1/calidad-datos", tags=["catalogos"])
def data_quality(conn: Connection = Depends(get_connection)):
    return provider_quality(conn)


@app.get("/api/v1/catalogos/contables", tags=["catalogos"])
def accounting_catalogs(conn: Connection = Depends(get_connection)):
    return list_accounting_catalogs(conn)


@app.post("/api/v1/catalogos/subcategorias", tags=["catalogos"])
def upsert_subcategory(
    data: SubcategoriaCatalogoRequest,
    conn: Connection = Depends(get_connection),
):
    payload = data.model_dump(mode="python")
    actor = payload.pop("actualizado_por")
    return save_subcategory(conn, payload, actor)


@app.get("/api/v1/gastos-fijos", tags=["catalogos"])
def fixed_expenses(conn: Connection = Depends(get_connection)):
    return list_fixed_expenses(conn)


@app.post("/api/v1/gastos-fijos", tags=["catalogos"])
def upsert_fixed_expense(
    data: GastoFijoRequest,
    conn: Connection = Depends(get_connection),
):
    payload = data.model_dump(mode="python")
    actor = payload.pop("actualizado_por")
    return save_fixed_expense(conn, payload, actor)


@app.get("/api/v1/entrenamiento/resumen", tags=["entrenamiento"])
def learning_summary(conn: Connection = Depends(get_connection)):
    return training_summary(conn)


@app.post("/api/v1/proveedores/importar", tags=["catalogos"])
async def import_providers(
    archivo: UploadFile = File(...),
    confirmar: bool = Form(False),
    importado_por: str = Form(...),
    conn: Connection = Depends(get_connection),
):
    if not (archivo.filename or "").lower().endswith((".xlsx", ".csv", ".tsv")):
        raise DomainError("El catálogo debe ser XLSX, CSV o TSV.", 415)
    content = await archivo.read()
    await archivo.close()
    if len(content) > 10 * 1024 * 1024:
        raise DomainError("El catálogo supera el límite de 10 MB.", 413)
    rows = parse_provider_file(archivo.filename or "catalogo.xlsx", content)
    preview = preview_provider_import(conn, rows)
    if not confirmar:
        return {
            "filas": len(preview),
            "creados": sum(item["accion"] == "crear" for item in preview),
            "actualizados": sum(item["accion"] == "actualizar" for item in preview),
            "errores": sum(bool(item["errores"]) for item in preview),
            "detalle": preview,
        }
    return {"filas": len(preview), **apply_provider_import(conn, preview, importado_por)}


@app.get("/api/v1/analytics/resumen", tags=["analytics"])
def analytics_summary(conn: Connection = Depends(get_connection)):
    return get_analytics_summary(conn)


def _validate_analytics_filters(
    anio_iso: int | None,
    semana_iso: int | None,
    fecha_desde: date | None,
    fecha_hasta: date | None,
    categoria: str | None,
) -> dict:
    if (anio_iso is None) != (semana_iso is None):
        raise DomainError("Indique juntos el año y la semana ISO.", 422)
    if (fecha_desde is None) != (fecha_hasta is None):
        raise DomainError("Indique juntas las dos fechas del periodo.", 422)
    if anio_iso is not None and fecha_desde is not None:
        raise DomainError("Elija semana ISO o rango de fechas, no ambos.", 422)
    if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
        raise DomainError("La fecha inicial no puede ser posterior a la fecha final.", 422)
    if anio_iso is not None:
        try:
            date.fromisocalendar(anio_iso, semana_iso, 1)
        except ValueError as exc:
            raise DomainError("La semana ISO no existe para el año indicado.", 422) from exc
    normalized_category = categoria.upper() if categoria else None
    return {
        "anio_iso": anio_iso,
        "semana_iso": semana_iso,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "categoria": normalized_category,
    }


@app.get("/api/v1/analytics/dashboard", tags=["analytics"])
def analytics_dashboard(
    anio_iso: int | None = Query(default=None, ge=2000, le=2100),
    semana_iso: int | None = Query(default=None, ge=1, le=53),
    fecha_desde: date | None = Query(default=None),
    fecha_hasta: date | None = Query(default=None),
    categoria: str | None = Query(default=None),
    conn: Connection = Depends(get_connection),
):
    filters = _validate_analytics_filters(
        anio_iso, semana_iso, fecha_desde, fecha_hasta, categoria
    )
    return get_analytics_dashboard(conn, **filters)


@app.get("/api/v1/analytics/exportar.csv", tags=["analytics"])
def analytics_export(
    anio_iso: int | None = Query(default=None, ge=2000, le=2100),
    semana_iso: int | None = Query(default=None, ge=1, le=53),
    fecha_desde: date | None = Query(default=None),
    fecha_hasta: date | None = Query(default=None),
    categoria: str | None = Query(default=None),
    conn: Connection = Depends(get_connection),
):
    filters = _validate_analytics_filters(
        anio_iso, semana_iso, fecha_desde, fecha_hasta, categoria
    )
    rows = get_analytics_export_rows(conn, **filters)
    columns = [
        "tipo_documento", "folio", "fecha", "anio_iso", "semana_iso", "restaurante", "sucursal", "proveedor",
        "proveedor_rfc", "categoria", "subcategoria", "moneda",
        "subtotal", "descuento", "iva", "otros_impuestos", "total", "estado_fiscal",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=analytics-facturas.csv"},
    )


@app.get("/api/v1/finanzas/estado-resultados", tags=["finanzas"])
def weekly_income_statement(
    anio_iso: int | None = Query(default=None, ge=2000, le=2100),
    semana_iso: int | None = Query(default=None, ge=1, le=53),
    sucursal_clave: str | None = Query(default=None),
    conn: Connection = Depends(get_connection),
):
    if (anio_iso is None) != (semana_iso is None):
        raise DomainError("Indique juntos el año y la semana ISO.", 422)
    return get_weekly_statement(
        conn,
        anio_iso=anio_iso,
        semana_iso=semana_iso,
        sucursal_clave=sucursal_clave,
    )


@app.get("/api/v1/finanzas/reporte-compras.pdf", tags=["finanzas"])
def weekly_purchase_report(
    anio_iso: int = Query(ge=2000, le=2100),
    semana_iso: int = Query(ge=1, le=53),
    sucursal_clave: str | None = Query(default=None),
    conn: Connection = Depends(get_connection),
):
    content = build_weekly_purchase_report(
        conn,
        anio_iso=anio_iso,
        semana_iso=semana_iso,
        sucursal_clave=sucursal_clave,
    )
    scope = f"-{sucursal_clave.lower()}" if sucursal_clave else "-consolidado"
    filename = f"reporte-compras-{anio_iso}-s{semana_iso:02d}{scope}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/v1/finanzas/reporte-ejecutivo.pdf", tags=["finanzas"])
def weekly_executive_report(
    anio_iso: int = Query(ge=2000, le=2100),
    semana_iso: int = Query(ge=1, le=53),
    sucursal_clave: str | None = Query(default=None),
    conn: Connection = Depends(get_connection),
):
    content = build_weekly_executive_report(
        conn,
        anio_iso=anio_iso,
        semana_iso=semana_iso,
        sucursal_clave=sucursal_clave,
    )
    scope = f"-{sucursal_clave.lower()}" if sucursal_clave else "-consolidado"
    filename = f"reporte-financiero-{anio_iso}-s{semana_iso:02d}{scope}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/v1/finanzas/reporte-ejecutivo-vacio.pdf", tags=["finanzas"])
def blank_weekly_executive_report(
    sucursal_clave: str | None = Query(default=None),
):
    content = build_blank_executive_report(sucursal_clave=sucursal_clave)
    scope = f"-{sucursal_clave.lower()}" if sucursal_clave else "-consolidado"
    filename = f"plantilla-reporte-financiero{scope}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _report_csv_integers(value: str | None, *, field: str) -> list[int]:
    if not value:
        return []
    try:
        return [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise DomainError(f"{field} debe ser una lista separada por comas.", 422) from exc


def _report_csv_strings(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


@app.get("/api/v1/reportes-financieros/opciones", tags=["reportes-financieros"])
def financial_report_options(conn: Connection = Depends(get_connection)):
    return get_report_options(conn)


@app.get("/api/v1/reportes-financieros/resumen", tags=["reportes-financieros"])
def financial_report_preview(
    modo: Literal["mensual", "semanas"] = Query(default="mensual"),
    anio: int = Query(ge=2000, le=2100),
    mes: int | None = Query(default=None, ge=1, le=12),
    semanas: str | None = Query(default=None),
    sucursal_clave: str | None = Query(default=None),
    conn: Connection = Depends(get_connection),
):
    return build_report_summary(
        conn,
        mode=modo,
        year=anio,
        month=mes,
        weeks=_report_csv_integers(semanas, field="semanas"),
        branch=sucursal_clave,
    )


@app.get("/api/v1/reportes-financieros/reporte.pdf", tags=["reportes-financieros"])
def configurable_financial_report(
    modo: Literal["mensual", "semanas"] = Query(default="mensual"),
    anio: int = Query(ge=2000, le=2100),
    mes: int | None = Query(default=None, ge=1, le=12),
    semanas: str | None = Query(default=None),
    secciones: str | None = Query(default=None),
    sucursal_clave: str | None = Query(default=None),
    conn: Connection = Depends(get_connection),
):
    content = build_configurable_financial_report(
        conn,
        mode=modo,
        year=anio,
        month=mes,
        weeks=_report_csv_integers(semanas, field="semanas"),
        branch=sucursal_clave,
        sections=_report_csv_strings(secciones) or None,
    )
    scope = f"-{sucursal_clave.lower()}" if sucursal_clave else "-consolidado"
    period = f"{anio}-{mes:02d}" if modo == "mensual" and mes else f"{anio}-semanas"
    filename = f"reporte-financiero-{period}{scope}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/v1/finanzas/ventas", status_code=201, tags=["finanzas"])
def create_manual_sale(
    data: VentaManualRequest,
    conn: Connection = Depends(get_connection),
):
    payload = data.model_dump(mode="python")
    actor = payload.pop("registrada_por")
    return register_sale(conn, payload, actor)


@app.get("/api/v1/finanzas/ventas-desglose", tags=["finanzas"])
def sales_breakdown(
    anio_iso: int = Query(ge=2000, le=2100),
    semana_iso: int = Query(ge=1, le=53),
    sucursal_clave: str | None = Query(default=None),
    conn: Connection = Depends(get_connection),
):
    return get_sales_breakdown(
        conn,
        anio_iso=anio_iso,
        semana_iso=semana_iso,
        sucursal_clave=sucursal_clave,
    )


@app.post("/api/v1/finanzas/ventas-desglose", tags=["finanzas"])
def update_sales_breakdown(
    data: VentasDesgloseRequest,
    conn: Connection = Depends(get_connection),
):
    payload = data.model_dump(mode="python")
    actor = payload.pop("actualizada_por")
    return save_sales_breakdown(
        conn,
        branch_id=payload["sucursal_id"],
        rows=payload["filas"],
        actor=actor,
        expenses=payload.get("gastos"),
        source_filename=payload.get("archivo_origen"),
    )


@app.post("/api/v1/finanzas/ventas-desglose/imagen", tags=["finanzas"], include_in_schema=False)
@app.post("/api/v1/finanzas/ventas-desglose/archivo", tags=["finanzas"])
async def preview_sales_file(
    archivo: UploadFile = File(...),
    sucursal_clave: str = Form(...),
    anio_iso: int = Form(default=date.today().year),
    semana_iso: int | None = Form(default=None),
    conn: Connection = Depends(get_connection),
    settings: Settings = Depends(get_settings),
):
    image_types = {"image/png", "image/jpeg", "image/webp"}
    xlsx_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    suffix = Path(archivo.filename or "").suffix.lower()
    is_xlsx = suffix == ".xlsx" and archivo.content_type in {xlsx_type, "application/octet-stream"}
    if archivo.content_type not in image_types and not is_xlsx:
        raise DomainError("El archivo de ventas debe ser PNG, JPG, WEBP o XLSX.", 415)
    content = await archivo.read()
    await archivo.close()
    if not content:
        raise DomainError("El archivo está vacío.", 422)
    if len(content) > 12 * 1024 * 1024:
        raise DomainError("El archivo supera el límite de 12 MB.", 413)
    branch = conn.execute(
        """
        SELECT id, clave, nombre, restaurante
        FROM catalog.sucursales WHERE clave = %s AND activa
        """,
        (sucursal_clave,),
    ).fetchone()
    if not branch or branch["clave"] == "POR-ASIGNAR":
        raise DomainError("Seleccione una sucursal operativa antes de analizar la imagen.", 422)
    temp_path = None
    try:
        if is_xlsx:
            parsed = await run_in_threadpool(
                parse_sales_xlsx,
                content,
                expected_year=anio_iso,
                expected_week=semana_iso,
            )
        else:
            temp_dir = settings.upload_dir / "ventas-temporales"
            temp_dir.mkdir(parents=True, exist_ok=True)
            image_suffix = {
                "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
            }[archivo.content_type]
            with tempfile.NamedTemporaryFile(delete=False, dir=temp_dir, suffix=image_suffix) as handle:
                handle.write(content)
                temp_path = Path(handle.name)
            engine = await run_in_threadpool(get_ocr_engine)
            document = await run_in_threadpool(engine.read, str(temp_path))
            parsed = parse_sales_image(document, str(temp_path))
        return {
            "periodo": {
                "anio_iso": parsed["anio_iso"],
                "semana_iso": parsed["semana_iso"],
                "fecha_desde": date.fromisocalendar(parsed["anio_iso"], parsed["semana_iso"], 1),
                "fecha_hasta": date.fromisocalendar(parsed["anio_iso"], parsed["semana_iso"], 7),
            },
            "sucursal": branch,
            "editable": True,
            "filas": parsed["filas"],
            "gastos": parsed.get("gastos", []),
            "archivo_origen": archivo.filename,
            "ocr": {
                "confianza": parsed["confianza_ocr"],
                "motor": parsed["proveedor_ocr"],
                "origen": "xlsx" if is_xlsx else "imagen",
                "advertencias": parsed["advertencias"],
                "conciliacion": parsed["conciliacion"],
            },
        }
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


@app.post("/api/v1/lotes", response_model=LoteCreado, status_code=201, tags=["lotes"])
async def upload_batch(
    archivo: UploadFile = File(...),
    sucursal_clave: str = Form(...),
    creada_por: str = Form(...),
    conn: Connection = Depends(get_connection),
    settings: Settings = Depends(get_settings),
):
    if archivo.content_type != "application/pdf":
        raise DomainError("La carga multipágina requiere un archivo PDF.", 415)
    original_path, digest, _ = await save_upload(archivo, settings)
    batch_id = uuid4()
    pages = []
    try:
        pages = split_pdf(original_path, settings.upload_dir, batch_id, settings.max_pdf_pages)
        return create_batch(
            conn,
            batch_id=batch_id,
            sucursal_clave=sucursal_clave,
            original_path=str(original_path.resolve()),
            original_name=archivo.filename or "lote.pdf",
            original_sha256=digest,
            created_by=creada_por,
            pages=pages,
        )
    except Exception:
        original_path.unlink(missing_ok=True)
        batch_dir = settings.upload_dir / "lotes" / str(batch_id)
        if batch_dir.exists():
            shutil.rmtree(batch_dir)
        raise


@app.get("/api/v1/lotes", response_model=list[LoteResumen], tags=["lotes"])
def batches(
    limit: int = Query(default=20, ge=1, le=100),
    conn: Connection = Depends(get_connection),
):
    return list_batches(conn, limit)


@app.post("/api/v1/lotes/{lote_id}/procesar", status_code=202, tags=["lotes"])
def process_batch(lote_id: UUID, conn: Connection = Depends(get_connection)):
    batch = conn.execute("SELECT estado::text FROM core.lotes_carga WHERE id = %s", (lote_id,)).fetchone()
    if not batch:
        raise DomainError("Lote no encontrado.", 404)
    if batch["estado"] == "cancelado":
        raise DomainError("El lote fue cancelado y no puede procesarse.", 409)
    started = start_batch_job(lote_id)
    return {
        "lote_id": lote_id,
        "estado": "procesando" if started or is_batch_active(lote_id) else "pendiente",
        "iniciado": started,
    }


@app.post("/api/v1/lotes/{lote_id}/cancelar", tags=["lotes"])
def cancel_processing_batch(
    lote_id: UUID,
    data: CancelarLoteRequest,
    conn: Connection = Depends(get_connection),
):
    result = cancel_batch(conn, lote_id, data.cancelado_por)
    conn.commit()
    return result


@app.delete("/api/v1/lotes/{lote_id}", tags=["lotes"])
def delete_cancelled_batch(
    lote_id: UUID,
    data: EliminarLoteRequest,
    conn: Connection = Depends(get_connection),
    settings: Settings = Depends(get_settings),
):
    batch = conn.execute(
        "SELECT estado::text FROM core.lotes_carga WHERE id = %s FOR UPDATE",
        (lote_id,),
    ).fetchone()
    if not batch:
        raise DomainError("Lote no encontrado.", 404)
    if batch["estado"] != "cancelado":
        raise DomainError("Primero detenga el procesamiento antes de eliminar el lote.", 409)
    invoice_ids = [
        row["id"] for row in conn.execute(
            "SELECT id FROM core.facturas WHERE lote_id = %s ORDER BY pagina_origen",
            (lote_id,),
        ).fetchall()
    ]
    if not invoice_ids:
        raise DomainError("El lote ya no contiene documentos.", 409)
    result = delete_pending_invoices(conn, invoice_ids, data.eliminado_por)
    conn.commit()
    upload_root = settings.upload_dir.resolve()
    removed_files = 0
    removed_paths = result.pop("archivos") + result.pop("lotes_eliminados")
    parent_dirs: set[Path] = set()
    for raw_path in removed_paths:
        path = Path(raw_path).resolve()
        if path.is_relative_to(upload_root) and path.is_file():
            parent_dirs.add(path.parent)
            path.unlink()
            removed_files += 1
    for directory in sorted(parent_dirs, key=lambda item: len(item.parts), reverse=True):
        if directory != upload_root and directory.is_relative_to(upload_root):
            try:
                directory.rmdir()
            except OSError:
                pass
    return {**result, "archivos_eliminados": removed_files}


@app.post("/api/v1/lotes/{lote_id}/reprocesar", status_code=202, tags=["lotes"])
def reprocess_pending_batch(lote_id: UUID, conn: Connection = Depends(get_connection)):
    batch = conn.execute("SELECT estado::text FROM core.lotes_carga WHERE id = %s", (lote_id,)).fetchone()
    if not batch:
        raise DomainError("Lote no encontrado.", 404)
    if batch["estado"] == "cancelado":
        raise DomainError("El lote fue cancelado y no puede reprocesarse.", 409)
    if is_batch_active(lote_id):
        raise DomainError("El lote ya se está procesando.", 409)
    rows = conn.execute(
        """
        UPDATE core.facturas
        SET estado = 'recibida', error_codigo = NULL, error_detalle = NULL,
            actualizada_en = now()
        WHERE lote_id = %s AND estado NOT IN ('aprobada', 'rechazada')
        RETURNING id
        """,
        (lote_id,),
    ).fetchall()
    conn.commit()
    started = bool(rows) and start_batch_job(lote_id)
    return {
        "lote_id": lote_id,
        "facturas_reiniciadas": len(rows),
        "estado": "procesando" if started else "sin_pendientes",
    }


@app.post("/api/v1/lotes/{lote_id}/reclasificar", tags=["clasificacion"])
def reclassify_existing_batch(lote_id: UUID, conn: Connection = Depends(get_connection)):
    exists = conn.execute("SELECT 1 FROM core.lotes_carga WHERE id = %s", (lote_id,)).fetchone()
    if not exists:
        raise DomainError("Lote no encontrado.", 404)
    results = reclassify_batch(conn, lote_id)
    counts: dict[str, int] = {}
    for result in results:
        counts[result["tipo"]] = counts.get(result["tipo"], 0) + 1
    return {"lote_id": lote_id, "clasificadas": len(results), "por_tipo": counts}


@app.post(
    "/api/v1/facturas/{factura_id}/aprobar",
    response_model=DecisionResultado,
    tags=["revision"],
)
def approve_invoice(
    factura_id: UUID,
    data: AprobarRequest,
    conn: Connection = Depends(get_connection),
):
    return decide_invoice(
        conn, factura_id, actor=data.revisada_por, decision="aprobada",
        comment=data.comentario, force_as_expense=data.forzar_como_gasto,
        remember_alias=data.recordar_alias,
        remember_classification=data.recordar_clasificacion,
        periodification=data.periodificacion.model_dump(mode="python") if data.periodificacion else None,
        remember_periodification=data.recordar_periodificacion,
    )


@app.post(
    "/api/v1/facturas/{factura_id}/corregir",
    response_model=DecisionResultado,
    tags=["revision"],
)
def correct_invoice(
    factura_id: UUID,
    data: CorregirRequest,
    conn: Connection = Depends(get_connection),
):
    return decide_invoice(
        conn,
        factura_id,
        actor=data.revisada_por,
        decision="corregida_y_aprobada",
        comment=data.comentario,
        corrections=[item.model_dump(mode="json") for item in data.correcciones],
        force_as_expense=data.forzar_como_gasto,
        remember_alias=data.recordar_alias,
        remember_classification=data.recordar_clasificacion,
        periodification=data.periodificacion.model_dump(mode="python") if data.periodificacion else None,
        remember_periodification=data.recordar_periodificacion,
    )


@app.post(
    "/api/v1/facturas/{factura_id}/editar",
    response_model=DecisionResultado,
    tags=["facturas"],
)
def edit_invoice(
    factura_id: UUID,
    data: EditarFacturaRequest,
    conn: Connection = Depends(get_connection),
):
    return edit_approved_invoice(
        conn,
        factura_id,
        actor=data.revisada_por,
        comment=data.comentario,
        corrections=[item.model_dump(mode="json") for item in data.correcciones],
        generates_expense=data.genera_gasto,
        remember_alias=data.recordar_alias,
        remember_classification=data.recordar_clasificacion,
        periodification=data.periodificacion.model_dump(mode="python") if data.periodificacion else None,
        remember_periodification=data.recordar_periodificacion,
    )


@app.post(
    "/api/v1/facturas/{factura_id}/rechazar",
    response_model=DecisionResultado,
    tags=["revision"],
)
def reject_invoice(
    factura_id: UUID,
    data: RechazarRequest,
    conn: Connection = Depends(get_connection),
):
    return decide_invoice(
        conn, factura_id, actor=data.revisada_por, decision="rechazada", comment=data.comentario
    )
