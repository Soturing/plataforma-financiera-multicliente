from datetime import date
import json

import psycopg
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from apoyo_db import conexion_pruebas


client = TestClient(app)


def _catalog_values():
    catalogs = client.get("/api/v1/catalogos").json()
    category = next(item for item in catalogs["categorias"] if item["clave"] == "VARIABLES_OPERATIVOS")
    return category["id"]


def _cleanup():
    with conexion_pruebas() as conn:
        conn.execute(
            "DELETE FROM core.comprobantes_internos WHERE creado_por LIKE 'pytest-recibos%'"
        )
        conn.execute(
            "DELETE FROM catalog.gastos_fijos WHERE proveedor_id IN "
            "(SELECT id FROM catalog.proveedores WHERE nombre_normalizado = 'Proveedor Informal Pytest')"
        )
        conn.execute(
            "DELETE FROM catalog.sucursales WHERE clave = 'PYTEST-02'"
        )


def _payload(total="8500.00", payment="transferencia"):
    category_id = _catalog_values()
    return {
        "sucursal_clave": "DEMO-A",
        "proveedor_nombre": "Proveedor Informal Pytest",
        "fecha_gasto": date.today().isoformat(),
        "concepto": "Compra de insumos sin CFDI",
        "metodo_pago": payment,
        "total": total,
        "categoria_id": category_id,
        "creado_por": "pytest-recibos",
        "rol_creador": "capturista",
    }


def test_cash_requires_provider_signature():
    _cleanup()
    response = client.post("/api/v1/comprobantes-internos", data=_payload(payment="efectivo"))
    assert response.status_code == 422, response.text
    assert "firma" in response.json()["detail"].lower()


def test_one_approval_publishes_receipt_and_generates_pdf():
    _cleanup()
    try:
        created = client.post("/api/v1/comprobantes-internos", data=_payload())
        assert created.status_code == 201, created.text
        receipt = created.json()
        assert receipt["folio"].startswith("CI-")
        assert receipt["numero_documento"] == date.today().strftime("%d%m%Y")
        assert receipt["numero_documento_origen"] == "fecha"
        assert receipt["estado"] == "pendiente_aprobacion"
        assert receipt["aprobaciones_requeridas"] == 1

        approved = client.post(
            f"/api/v1/comprobantes-internos/{receipt['id']}/aprobar",
            json={"autorizada_por": "gerente-pytest", "comentario": "Autorizado"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["estado"] == "aprobado"

        with conexion_pruebas() as conn:
            movement = conn.execute(
                """
                SELECT tipo_documento, total, estado_fiscal
                FROM analytics.movimientos_gasto WHERE movimiento_id = %s
                """,
                (receipt["id"],),
            ).fetchone()
        assert movement == ("comprobante_interno", 8500, "no_deducible")

        pdf = client.get(f"/api/v1/comprobantes-internos/{receipt['id']}/pdf")
        assert pdf.status_code == 200, pdf.text
        assert pdf.content.startswith(b"%PDF")
    finally:
        _cleanup()


def test_one_approval_is_enough_above_ten_thousand():
    _cleanup()
    try:
        created = client.post("/api/v1/comprobantes-internos", data=_payload("25000.00"))
        assert created.status_code == 201, created.text
        receipt_id = created.json()["id"]
        approved = client.post(
            f"/api/v1/comprobantes-internos/{receipt_id}/aprobar",
            json={"autorizada_por": "gerente-uno"},
        )
        assert approved.status_code == 200
        assert approved.json()["estado"] == "aprobado"
        assert approved.json()["aprobaciones_requeridas"] == 1

        repeated = client.post(
            f"/api/v1/comprobantes-internos/{receipt_id}/aprobar",
            json={"autorizada_por": "gerente-uno"},
        )
        assert repeated.status_code == 409
    finally:
        _cleanup()


def test_limit_and_distribution_validation():
    _cleanup()
    allowed = client.post("/api/v1/comprobantes-internos", data=_payload("300000.00"))
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["aprobaciones_requeridas"] == 1

    too_large = client.post("/api/v1/comprobantes-internos", data=_payload("300000.01"))
    assert too_large.status_code == 422
    assert "$300,000" in too_large.json()["detail"]

    invalid_split = _payload("1000.00")
    invalid_split["distribuciones"] = '[{"sucursal_clave":"DEMO-A","monto":"999.00"}]'
    response = client.post("/api/v1/comprobantes-internos", data=invalid_split)
    assert response.status_code == 422
    assert "sumar exactamente" in response.json()["detail"]

    crossed = _payload("1000.00")
    crossed["distribuciones"] = '[{"sucursal_clave":"DEMO-A","monto":"500.00"},{"sucursal_clave":"DEMO-B","monto":"500.00"}]'
    response = client.post("/api/v1/comprobantes-internos", data=crossed)
    assert response.status_code == 422
    assert "pagos cruzados" in response.json()["detail"]


def test_captured_note_number_is_searchable():
    _cleanup()
    try:
        payload = _payload("750.00")
        payload["numero_documento"] = "NOTA-IRR-4482"
        created = client.post("/api/v1/comprobantes-internos", data=payload)
        assert created.status_code == 201, created.text
        receipt = created.json()
        assert receipt["numero_documento"] == "NOTA-IRR-4482"
        assert receipt["numero_documento_origen"] == "capturado"

        found = client.get(
            "/api/v1/documentos/buscar", params={"numero": "NOTA-IRR-4482"}
        )
        assert found.status_code == 200, found.text
        assert any(item["id"] == receipt["id"] for item in found.json())
    finally:
        _cleanup()


def test_fixed_internal_receipt_can_be_periodified():
    _cleanup()
    try:
        catalogs = client.get("/api/v1/catalogos").json()
        fixed = next(item for item in catalogs["categorias"] if item["clave"] == "FIJOS")
        payload = _payload("40000.00")
        assert client.post("/api/v1/comprobantes-internos", data=_payload("100.00")).status_code == 201
        provider_id = next(
            item["id"] for item in client.get("/api/v1/proveedores").json()
            if item["nombre_normalizado"] == "Proveedor Informal Pytest"
        )
        payload.update({
            "categoria_id": fixed["id"],
            "fecha_gasto": "2026-08-28",
            "periodificacion": json.dumps({
                "tipo": "mensual",
                "periodo_desde": "2026-08-01",
                "periodo_hasta": "2026-08-31",
            }),
        })
        blocked = client.post("/api/v1/comprobantes-internos", data=payload)
        assert blocked.status_code == 422, blocked.text
        listed = client.post(
            "/api/v1/gastos-fijos",
            json={"proveedor_id": provider_id, "actualizado_por": "pytest-recibos"},
        )
        assert listed.status_code == 200, listed.text
        created = client.post("/api/v1/comprobantes-internos", data=payload)
        assert created.status_code == 201, created.text
        receipt_id = created.json()["id"]
        approved = client.post(
            f"/api/v1/comprobantes-internos/{receipt_id}/aprobar",
            json={"autorizada_por": "gerente-periodo-1"},
        )
        assert approved.status_code == 200, approved.text
        with conexion_pruebas() as conn:
            rows = conn.execute(
                """
                SELECT ps.semana_iso, ps.monto
                FROM finance.periodificacion_semanas ps
                JOIN finance.periodificaciones_gasto pg ON pg.id = ps.periodificacion_id
                WHERE pg.comprobante_id = %s ORDER BY ps.semana_iso
                """,
                (receipt_id,),
            ).fetchall()
        assert rows == [(32, 10000), (33, 10000), (34, 10000), (35, 10000)]
    finally:
        _cleanup()
