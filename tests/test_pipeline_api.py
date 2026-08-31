from io import BytesIO
from uuid import UUID

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from pypdf import PdfWriter

from app.config import get_settings
from app.main import app
from app.repository import register_uuid_duplicates


def one_page_pdf(label: str) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": label})
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def cleanup_test_invoices():
    with psycopg.connect(get_settings().database_url) as conn:
        conn.execute(
            """
            DELETE FROM core.documentos_duplicados
            WHERE factura_original_id IN (SELECT id FROM core.facturas WHERE creada_por = 'pytest')
               OR factura_duplicada_id IN (SELECT id FROM core.facturas WHERE creada_por = 'pytest')
            """
        )
        conn.execute(
            """
            DELETE FROM core.facturas_finales
            WHERE factura_id IN (SELECT id FROM core.facturas WHERE creada_por = 'pytest')
            """
        )
        conn.execute("DELETE FROM core.facturas WHERE creada_por = 'pytest'")
        conn.execute(
            """
            DELETE FROM catalog.proveedores
            WHERE nombre_normalizado = 'Proveedor Editado Después Pytest'
              AND NOT EXISTS (
                  SELECT 1 FROM core.facturas_finales
                  WHERE proveedor_id = catalog.proveedores.id
              )
            """
        )


def test_bulk_upload_separates_exact_duplicate_until_manual_discard():
    cleanup_test_invoices()
    client = TestClient(app)
    try:
        same_invoice = one_page_pdf("same-invoice")
        original = client.post(
            "/api/v1/facturas",
            data={"sucursal_clave": "DEMO-A", "creada_por": "pytest"},
            files={"archivo": ("original.pdf", BytesIO(same_invoice), "application/pdf")},
        )
        assert original.status_code == 201, original.text

        upload = client.post(
            "/api/v1/documentos/carga-masiva",
            data={"sucursal_clave": "DEMO-A", "creada_por": "pytest"},
            files=[
                ("archivos", ("copia.pdf", BytesIO(same_invoice), "application/pdf")),
                ("archivos", ("nueva.pdf", BytesIO(one_page_pdf("different-invoice")), "application/pdf")),
            ],
        )
        assert upload.status_code == 201, upload.text
        assert len(upload.json()["duplicados"]) == 1
        duplicate_id = upload.json()["duplicados"][0]["id"]

        duplicates = client.get("/api/v1/duplicados")
        assert duplicates.status_code == 200, duplicates.text
        assert any(row["id"] == duplicate_id and row["criterio"] == "sha256" for row in duplicates.json())

        discarded = client.post(
            "/api/v1/duplicados/descartar",
            json={"duplicado_ids": [duplicate_id], "descartado_por": "pytest"},
        )
        assert discarded.status_code == 200, discarded.text
        assert discarded.json()["descartados"] == 1
        assert all(row["id"] != duplicate_id for row in client.get("/api/v1/duplicados").json())
    finally:
        cleanup_test_invoices()


def test_uuid_duplicate_is_removed_from_review_queue():
    cleanup_test_invoices()
    client = TestClient(app)
    try:
        invoice_ids = []
        for index in (1, 2):
            created = client.post(
                "/api/v1/facturas",
                data={"sucursal_clave": "DEMO-A", "creada_por": "pytest"},
                files={"archivo": (f"uuid-{index}.pdf", BytesIO(one_page_pdf(f"uuid-{index}")), "application/pdf")},
            )
            assert created.status_code == 201, created.text
            invoice_id = created.json()["id"]
            invoice_ids.append(invoice_id)
            processed = client.post(
                f"/api/v1/facturas/{invoice_id}/procesar-simulado",
                json={
                    "proveedor": "Proveedor Ficticio Base",
                    "fecha_emision": "2026-08-07",
                    "subtotal": "100.00",
                    "iva": "16.00",
                    "total": "116.00",
                },
            )
            assert processed.status_code == 200, processed.text

        fiscal_uuid = UUID("11111111-2222-4333-8444-555555555555")
        with psycopg.connect(get_settings().database_url, row_factory=dict_row) as conn:
            conn.execute(
                "UPDATE ai.interpretaciones SET uuid_fiscal = %s WHERE factura_id = ANY(%s)",
                (fiscal_uuid, invoice_ids),
            )
            registered = register_uuid_duplicates(conn, fiscal_uuid)
            assert len(registered) == 1

        queue_ids = {row["id"] for row in client.get("/api/v1/revision").json()}
        assert len(queue_ids.intersection(invoice_ids)) == 1
        duplicate = next(
            row for row in client.get("/api/v1/duplicados").json()
            if row["criterio"] == "uuid_fiscal" and row["factura_duplicada_id"] in invoice_ids
        )
        discarded = client.post(
            "/api/v1/duplicados/descartar",
            json={"duplicado_ids": [duplicate["id"]], "descartado_por": "pytest"},
        )
        assert discarded.status_code == 200, discarded.text
    finally:
        cleanup_test_invoices()


def test_accounting_catalogs_match_review_model():
    client = TestClient(app)
    response = client.get("/api/v1/catalogos")
    assert response.status_code == 200, response.text
    catalogs = response.json()
    assert [item["clave"] for item in catalogs["categorias"]] == ["FIJOS", "VARIABLES"]
    assert {"RENTA", "MANTENIMIENTO", "INSUMOS", "BEBIDAS"}.issubset(
        {item["clave"] for item in catalogs["subcategorias"]}
    )
    assert {"COCINA", "BARRA", "ADMINISTRACION", "GENERAL"}.issubset(
        {item["clave"] for item in catalogs["centros_costo"]}
    )


def test_pipeline_upload_process_approve():
    cleanup_test_invoices()
    client = TestClient(app)
    try:
        created = client.post(
            "/api/v1/facturas",
            data={"sucursal_clave": "DEMO-A", "creada_por": "pytest"},
            files={"archivo": ("factura.jpg", BytesIO(b"demo-image"), "image/jpeg")},
        )
        assert created.status_code == 201, created.text
        invoice_id = created.json()["id"]

        processed = client.post(
            f"/api/v1/facturas/{invoice_id}/procesar-simulado",
            json={
                "proveedor": "Proveedor Ficticio Base",
                "fecha_emision": "2026-08-07",
                "subtotal": "10000.00",
                "iva": "1600.00",
                "total": "11600.00",
            },
        )
        assert processed.status_code == 200, processed.text
        assert processed.json()["estado"] == "requiere_revision"

        case = client.get(f"/api/v1/facturas/{invoice_id}/expediente")
        assert case.status_code == 200, case.text
        assert case.json()["factura"]["proveedor"] == "Proveedor Ficticio Base"
        assert case.json()["factura"]["folio"] == "07082026"
        assert len(case.json()["validaciones"]) == 3

        found = client.get("/api/v1/documentos/buscar", params={"numero": "07082026"})
        assert found.status_code == 200, found.text
        assert any(item["id"] == invoice_id for item in found.json())

        source_file = client.get(f"/api/v1/facturas/{invoice_id}/archivo")
        assert source_file.status_code == 200
        assert source_file.content == b"demo-image"

        review_item = client.get(f"/api/v1/facturas/{invoice_id}")
        assert review_item.status_code == 200, review_item.text
        assert review_item.json()["estado"] == "requiere_revision"

        approved = client.post(
            f"/api/v1/facturas/{invoice_id}/aprobar",
            json={"revisada_por": "pytest"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["estado"] == "aprobada"

        archive = client.get("/api/v1/documentos/archivo")
        assert archive.status_code == 200, archive.text
        assert any(item["id"] == invoice_id for item in archive.json())
        archived_match = client.get("/api/v1/documentos/archivo", params={"q": "Proveedor Ficticio Base"})
        assert archived_match.status_code == 200, archived_match.text
        assert any(item["id"] == invoice_id for item in archived_match.json())

        with psycopg.connect(get_settings().database_url) as conn:
            count = conn.execute(
                "SELECT count(*) FROM analytics.facturas_consumo WHERE factura_id = %s",
                (invoice_id,),
            ).fetchone()[0]
            assert count == 1

        dashboard = client.get("/api/v1/analytics/dashboard")
        assert dashboard.status_code == 200, dashboard.text
        assert dashboard.json()["aprobado"]["facturas"] >= 1
        assert any(
                item["nombre"] == "Variables"
            for item in dashboard.json()["aprobado"]["categorias"]
        )

        exported = client.get("/api/v1/analytics/exportar.csv")
        assert exported.status_code == 200, exported.text
        assert "analytics-facturas.csv" in exported.headers["content-disposition"]
        assert "Proveedor Ficticio Base" in exported.text
    finally:
        cleanup_test_invoices()


def test_approved_invoice_can_be_edited_without_duplicate_analytics():
    cleanup_test_invoices()
    client = TestClient(app)
    try:
        created = client.post(
            "/api/v1/facturas",
            data={"sucursal_clave": "DEMO-A", "creada_por": "pytest"},
            files={"archivo": ("factura-editable.jpg", BytesIO(b"editable-invoice"), "image/jpeg")},
        )
        assert created.status_code == 201, created.text
        invoice_id = created.json()["id"]
        processed = client.post(
            f"/api/v1/facturas/{invoice_id}/procesar-simulado",
            json={
                "proveedor": "Proveedor Ficticio Base",
                "fecha_emision": "2026-08-10",
                "subtotal": "1000.00",
                "iva": "160.00",
                "total": "1160.00",
            },
        )
        assert processed.status_code == 200, processed.text
        approved = client.post(
            f"/api/v1/facturas/{invoice_id}/aprobar",
            json={"revisada_por": "pytest"},
        )
        assert approved.status_code == 200, approved.text

        edited = client.post(
            f"/api/v1/facturas/{invoice_id}/editar",
            json={
                "revisada_por": "pytest-editor",
                "correcciones": [
                    {"campo": "proveedor_nombre", "valor": "Proveedor Editado Después Pytest"},
                    {"campo": "folio", "valor": "FAC-CORREGIDA-01"},
                    {"campo": "total", "valor": "1250.00"},
                ],
            },
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["estado"] == "aprobada"

        case = client.get(f"/api/v1/facturas/{invoice_id}/expediente")
        assert case.status_code == 200, case.text
        assert case.json()["factura"]["proveedor"] == "Proveedor Editado Después Pytest"
        assert case.json()["factura"]["folio"] == "FAC-CORREGIDA-01"
        assert case.json()["factura"]["total"] == 1250.0

        with psycopg.connect(get_settings().database_url) as conn:
            versions = conn.execute(
                """
                SELECT version, vigente, total
                FROM core.facturas_finales
                WHERE factura_id = %s ORDER BY version
                """,
                (invoice_id,),
            ).fetchall()
            analytics = conn.execute(
                """
                SELECT proveedor, folio, total
                FROM analytics.movimientos_gasto
                WHERE documento_origen_id = %s
                """,
                (invoice_id,),
            ).fetchall()
            corrections = conn.execute(
                "SELECT count(*) FROM audit.correcciones WHERE factura_id = %s",
                (invoice_id,),
            ).fetchone()[0]
        assert versions == [(1, False, 1160), (2, True, 1250)]
        assert analytics == [("Proveedor Editado Después Pytest", "FAC-CORREGIDA-01", 1250)]
        assert corrections == 3

        removed_from_analytics = client.post(
            f"/api/v1/facturas/{invoice_id}/editar",
            json={
                "revisada_por": "pytest-editor",
                "genera_gasto": False,
                "comentario": "No debe afectar el análisis financiero",
            },
        )
        assert removed_from_analytics.status_code == 200, removed_from_analytics.text
        with psycopg.connect(get_settings().database_url) as conn:
            assert conn.execute(
                "SELECT count(*) FROM analytics.movimientos_gasto WHERE documento_origen_id = %s",
                (invoice_id,),
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT genera_gasto FROM core.facturas_finales WHERE factura_id = %s AND vigente",
                (invoice_id,),
            ).fetchone()[0] is False
    finally:
        cleanup_test_invoices()


def test_correction_allows_provider_branch_reference_and_optional_amounts():
    cleanup_test_invoices()
    client = TestClient(app)
    try:
        created = client.post(
            "/api/v1/facturas",
            data={"sucursal_clave": "DEMO-A", "creada_por": "pytest"},
            files={"archivo": ("factura-total.jpg", BytesIO(b"demo-total-only"), "image/jpeg")},
        )
        assert created.status_code == 201, created.text
        invoice_id = created.json()["id"]

        processed = client.post(
            f"/api/v1/facturas/{invoice_id}/procesar-simulado",
            json={
                "proveedor": "Proveedor Ficticio Base",
                "fecha_emision": "2026-08-08",
                "subtotal": "100.00",
                "iva": "16.00",
                "total": "116.00",
            },
        )
        assert processed.status_code == 200, processed.text

        catalogs = client.get("/api/v1/catalogos").json()
        demo_a_id = next(item["id"] for item in catalogs["sucursales"] if item["clave"] == "DEMO-A")

        corrected = client.post(
            f"/api/v1/facturas/{invoice_id}/corregir",
            json={
                "revisada_por": "pytest",
                "correcciones": [
                    {"campo": "proveedor_nombre", "valor": "Proveedor Editado Demo"},
                    {"campo": "sucursal_id", "valor": demo_a_id},
                    {"campo": "folio", "valor": "FAC-DEMO-A-8801"},
                    {"campo": "subtotal", "valor": None},
                    {"campo": "iva", "valor": None},
                ],
            },
        )
        assert corrected.status_code == 200, corrected.text
        assert corrected.json()["estado"] == "aprobada"

        with psycopg.connect(get_settings().database_url) as conn:
            row = conn.execute(
                """
                SELECT a.proveedor, a.subtotal, a.iva, a.total, a.categoria,
                       a.subcategoria, a.sucursal_clave, ff.folio
                FROM analytics.facturas_consumo a
                JOIN core.facturas_finales ff ON ff.id = a.factura_final_id
                WHERE a.factura_id = %s
                """,
                (invoice_id,),
            ).fetchone()
            assert row == (
                "Proveedor Editado Demo", None, None, 116, "Variables", None,
                "DEMO-A", "FAC-DEMO-A-8801",
            )
    finally:
        cleanup_test_invoices()


def test_reviewer_can_override_no_expense_classification():
    cleanup_test_invoices()
    client = TestClient(app)
    try:
        created = client.post(
            "/api/v1/facturas",
            data={"sucursal_clave": "DEMO-A", "creada_por": "pytest"},
            files={"archivo": ("clasificacion-manual.jpg", BytesIO(b"manual-expense"), "image/jpeg")},
        )
        assert created.status_code == 201, created.text
        invoice_id = created.json()["id"]

        processed = client.post(
            f"/api/v1/facturas/{invoice_id}/procesar-simulado",
            json={
                "proveedor": "Proveedor Ficticio Base",
                "fecha_emision": "2026-08-09",
                "subtotal": "200.00",
                "iva": "32.00",
                "total": "232.00",
            },
        )
        assert processed.status_code == 200, processed.text

        with psycopg.connect(get_settings().database_url) as conn:
            version = conn.execute(
                "SELECT max(version) + 1 FROM core.clasificaciones_documentales WHERE factura_id = %s",
                (invoice_id,),
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO core.clasificaciones_documentales (
                    factura_id, version, tipo, confianza, clasificador, reglas_version, evidencia
                ) VALUES (%s, %s, 'comprobante_pago', 0.9, 'pytest', 'test', '{}'::jsonb)
                """,
                (invoice_id, version),
            )

        blocked = client.post(
            f"/api/v1/facturas/{invoice_id}/aprobar",
            json={"revisada_por": "pytest"},
        )
        assert blocked.status_code == 422, blocked.text

        overridden = client.post(
            f"/api/v1/facturas/{invoice_id}/aprobar",
            json={"revisada_por": "pytest", "forzar_como_gasto": True},
        )
        assert overridden.status_code == 200, overridden.text
        assert overridden.json()["estado"] == "aprobada"

        with psycopg.connect(get_settings().database_url) as conn:
            classification = conn.execute(
                """
                SELECT tipo::text, clasificador, evidencia->>'tipo_anterior'
                FROM core.clasificaciones_documentales
                WHERE factura_id = %s ORDER BY version DESC LIMIT 1
                """,
                (invoice_id,),
            ).fetchone()
            assert classification == ("recibo", "revision_humana", "comprobante_pago")
            assert conn.execute(
                "SELECT count(*) FROM analytics.facturas_consumo WHERE factura_id = %s",
                (invoice_id,),
            ).fetchone()[0] == 1
    finally:
        cleanup_test_invoices()
