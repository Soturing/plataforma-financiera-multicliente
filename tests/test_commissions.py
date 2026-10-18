from decimal import Decimal

import psycopg
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from apoyo_db import conexion_pruebas


client = TestClient(app)
BRANCH = "PYTEST-COM"
ACTOR = "pytest-comisiones"


def cleanup():
    with conexion_pruebas() as conn:
        for table in ("finance.ventas", "finance.comision_parametros", "finance.comision_cierres"):
            conn.execute(
                f"DELETE FROM {table} WHERE sucursal_id IN (SELECT id FROM catalog.sucursales WHERE clave = %s)",
                (BRANCH,),
            )
        conn.execute("DELETE FROM catalog.sucursales WHERE clave = %s", (BRANCH,))


def setup_branch():
    cleanup()
    with conexion_pruebas() as conn:
        branch_id = conn.execute(
            "INSERT INTO catalog.sucursales (clave, nombre, restaurante) VALUES (%s, 'Pytest Comisiones', 'Pytest') RETURNING id",
            (BRANCH,),
        ).fetchone()[0]
        # Semana ISO 33 de 2026: del 10 al 16 de agosto.
        conn.execute(
            """
            INSERT INTO finance.ventas (
                sucursal_id, fecha, monto_neto, fuente, referencia, registrada_por,
                visa, amex, uber, rappi
            ) VALUES (%s, DATE '2026-08-12', 20000, 'manual', 'pytest-com', %s, 10000, 2000, 1000, 500)
            """,
            (branch_id, ACTOR),
        )


def parameter(concept, base, **values):
    body = {
        "sucursal_clave": BRANCH, "concepto": concept, "base": base,
        "actualizado_por": ACTOR, **values,
    }
    return client.post("/api/v1/finanzas/comisiones/parametros", json=body)


def week_commissions():
    response = client.get(
        "/api/v1/finanzas/estado-resultados",
        params={"anio_iso": 2026, "semana_iso": 33, "sucursal_clave": BRANCH},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_projection_uses_adjustable_percentages_and_monthly_amounts():
    setup_branch()
    try:
        assert parameter("VISA", "visa", porcentaje="0.02").status_code == 200
        assert parameter("BANCO", "credito", porcentaje="0.01").status_code == 200
        assert parameter("APPS", "uber", canal="UBER", porcentaje="0.30").status_code == 200
        assert parameter("APPS", "rappi", canal="RAPPI", porcentaje="0.10").status_code == 200
        assert parameter("SERVICIOS", "monto_mensual", monto_mensual="1000.00").status_code == 200

        data = week_commissions()
        items = {
            (row["proveedor"]): Decimal(str(row["monto_aplicado"]))
            for row in data["detalle_gastos"]["comisiones"]
        }
        assert items["Comisión Terminal Visa"] == Decimal("200.00")
        assert items["Comisión Banco"] == Decimal("120.00")
        assert items["Comisión Apps UBER"] == Decimal("300.00")
        assert items["Comisión Apps RAPPI"] == Decimal("50.00")
        assert items["Comisión Servicios"] == Decimal("250.00")  # 1000 entre 4 semanas de agosto
        assert Decimal(str(data["desglose_gastos"]["comisiones"])) == Decimal("920.00")
        assert all(row["estimado"] for row in data["detalle_gastos"]["comisiones"])
        assert Decimal(str(data["resumen"]["costos_variables"])) >= Decimal("920.00")

        # Editar el porcentaje cambia la proyección.
        assert parameter("VISA", "visa", porcentaje="0.03").status_code == 200
        items = {r["proveedor"]: Decimal(str(r["monto_aplicado"])) for r in week_commissions()["detalle_gastos"]["comisiones"]}
        assert items["Comisión Terminal Visa"] == Decimal("300.00")
    finally:
        cleanup()


def test_monthly_closing_replaces_projection_and_can_be_cleared():
    setup_branch()
    try:
        assert parameter("VISA", "visa", porcentaje="0.02").status_code == 200
        closing = client.post(
            "/api/v1/finanzas/comisiones/cierre",
            json={
                "sucursal_clave": BRANCH, "concepto": "VISA", "anio": 2026, "mes": 8,
                "importe_real": "1001.00", "actualizado_por": ACTOR,
            },
        )
        assert closing.status_code == 200, closing.text
        summary = closing.json()
        assert Decimal(str(summary["proyectado"])) == Decimal("200.00")
        assert Decimal(str(summary["real"])) == Decimal("1001.00")
        assert Decimal(str(summary["diferencia"])) == Decimal("801.00")

        rows = week_commissions()["detalle_gastos"]["comisiones"]
        visa = next(row for row in rows if row["proveedor"] == "Comisión Terminal Visa")
        assert visa["estimado"] is False
        assert visa["tipo_documento"] == "cierre_real"
        assert Decimal(str(visa["monto_aplicado"])) == Decimal("250.25")  # 1001.00 / 4 semanas

        cleared = client.post(
            "/api/v1/finanzas/comisiones/cierre",
            json={
                "sucursal_clave": BRANCH, "concepto": "VISA", "anio": 2026, "mes": 8,
                "importe_real": None, "actualizado_por": ACTOR,
            },
        )
        assert cleared.status_code == 200 and cleared.json()["real"] is None
        rows = week_commissions()["detalle_gastos"]["comisiones"]
        assert rows[0]["estimado"] is True
    finally:
        cleanup()


def test_parameter_validation():
    setup_branch()
    try:
        assert parameter("VISA", "visa").status_code == 422  # falta el porcentaje
        assert parameter("SERVICIOS", "monto_mensual").status_code == 422  # falta el monto
        assert parameter("VISA", "visa", canal="UBER", porcentaje="0.02").status_code == 422
        assert parameter("VISA", "visa", porcentaje="1.5").status_code == 422
    finally:
        cleanup()
