from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import psycopg
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.periodification import allocate_period, weeks_for_period
from apoyo_db import conexion_pruebas


client = TestClient(app)


def cleanup():
    paths = []
    with conexion_pruebas() as conn:
        paths = [
            Path(row[0]) for row in conn.execute(
                "SELECT archivo_url FROM core.facturas WHERE creada_por = 'pytest-periodificacion'"
            ).fetchall()
        ]
        conn.execute(
            "DELETE FROM core.facturas_finales WHERE factura_id IN "
            "(SELECT id FROM core.facturas WHERE creada_por = 'pytest-periodificacion')"
        )
        conn.execute("DELETE FROM core.facturas WHERE creada_por = 'pytest-periodificacion'")
        conn.execute(
            "DELETE FROM catalog.gastos_fijos WHERE proveedor_id IN "
            "(SELECT id FROM catalog.proveedores WHERE nombre_normalizado = 'IMSS Pytest')"
        )
    for path in paths:
        path.unlink(missing_ok=True)


def test_majority_day_rule_maps_august_2026_to_weeks_32_through_35():
    weeks = weeks_for_period("mensual", date(2026, 8, 1), date(2026, 8, 31))
    assert [(item["anio_iso"], item["semana_iso"]) for item in weeks] == [
        (2026, 32), (2026, 33), (2026, 34), (2026, 35),
    ]


def test_bimonthly_period_can_span_nine_weeks_and_rounds_remainder_last():
    rows = allocate_period(Decimal("100.00"), "bimestral", date(2026, 7, 1), date(2026, 8, 31))
    assert len(rows) == 9
    assert sum((row["monto"] for row in rows), Decimal("0")) == Decimal("100.00")
    assert rows[0]["monto"] == Decimal("11.11")
    assert rows[-1]["monto"] == Decimal("11.12")


def test_fixed_invoice_is_applied_retroactively_across_the_month():
    cleanup()
    try:
        with conexion_pruebas() as conn:
            baseline = dict(conn.execute(
                """
                SELECT semana_iso, gastos_fijos
                FROM finance.estado_resultados_semanal
                WHERE sucursal_clave = 'DEMO-A' AND anio_iso = 2026
                  AND semana_iso BETWEEN 32 AND 35 ORDER BY semana_iso
                """
            ).fetchall())
        created = client.post(
            "/api/v1/facturas",
            data={"sucursal_clave": "DEMO-A", "creada_por": "pytest-periodificacion"},
            files={"archivo": ("imss.jpg", BytesIO(b"periodification-test"), "image/jpeg")},
        )
        assert created.status_code == 201, created.text
        invoice_id = created.json()["id"]
        processed = client.post(
            f"/api/v1/facturas/{invoice_id}/procesar-simulado",
            json={
                "proveedor": "IMSS Pytest",
                "fecha_emision": "2026-08-20",
                "subtotal": "100000.00",
                "iva": "0",
                "total": "100000.00",
                "categoria_clave": "FIJOS",
                "subcategoria_clave": "SERVICIOS_FIJOS",
            },
        )
        assert processed.status_code == 200, processed.text
        blocked = client.post(
            f"/api/v1/facturas/{invoice_id}/aprobar",
            json={"revisada_por": "pytest-periodificacion"},
        )
        assert blocked.status_code == 422, blocked.text
        assert "lista de gastos fijos" in blocked.json()["detail"]
        provider_id = next(
            item["id"] for item in client.get("/api/v1/proveedores").json()
            if item["nombre_normalizado"] == "IMSS Pytest"
        )
        listed = client.post(
            "/api/v1/gastos-fijos",
            json={"proveedor_id": provider_id, "periodicidad": "mensual", "actualizado_por": "pytest-periodificacion"},
        )
        assert listed.status_code == 200, listed.text
        approved = client.post(
            f"/api/v1/facturas/{invoice_id}/aprobar",
            json={
                "revisada_por": "pytest-periodificacion",
                "periodificacion": {
                    "tipo": "mensual",
                    "periodo_desde": "2026-08-01",
                    "periodo_hasta": "2026-08-31",
                },
            },
        )
        assert approved.status_code == 200, approved.text

        with conexion_pruebas() as conn:
            schedule = conn.execute(
                """
                SELECT ps.semana_iso, ps.monto
                FROM finance.periodificacion_semanas ps
                JOIN finance.periodificaciones_gasto pg ON pg.id = ps.periodificacion_id
                WHERE pg.factura_id = %s ORDER BY ps.semana_iso
                """,
                (invoice_id,),
            ).fetchall()
            statement = conn.execute(
                """
                SELECT semana_iso, gastos_fijos
                FROM finance.estado_resultados_semanal
                WHERE sucursal_clave = 'DEMO-A' AND anio_iso = 2026
                  AND semana_iso BETWEEN 32 AND 35 ORDER BY semana_iso
                """
            ).fetchall()
        assert schedule == [(32, Decimal("25000.00")), (33, Decimal("25000.00")), (34, Decimal("25000.00")), (35, Decimal("25000.00"))]
        applied_delta = [
            (week, amount - baseline.get(week, Decimal("0")))
            for week, amount in statement
        ]
        assert applied_delta == schedule
    finally:
        cleanup()
