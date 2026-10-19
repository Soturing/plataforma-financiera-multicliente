from decimal import Decimal

import psycopg
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from apoyo_db import conexion_pruebas


client = TestClient(app)
BRANCH = "PYTEST-NOM"
ACTOR = "pytest-nomina"


def cleanup():
    with conexion_pruebas() as conn:
        for table in ("finance.ventas", "finance.nomina_semanal"):
            conn.execute(
                f"DELETE FROM {table} WHERE sucursal_id IN (SELECT id FROM catalog.sucursales WHERE clave = %s)",
                (BRANCH,),
            )
        conn.execute("DELETE FROM catalog.sucursales WHERE clave = %s", (BRANCH,))


def setup_branch():
    cleanup()
    with conexion_pruebas() as conn:
        branch_id = conn.execute(
            "INSERT INTO catalog.sucursales (clave, nombre, restaurante) VALUES (%s, 'Pytest Nomina', 'Pytest') RETURNING id",
            (BRANCH,),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO finance.ventas (sucursal_id, fecha, monto_neto, fuente, referencia, registrada_por)
            VALUES (%s, DATE '2026-08-12', 20000, 'manual', 'pytest-nom', %s)
            """,
            (branch_id, ACTOR),
        )


def save(amount, week=33, note=None):
    return client.post(
        "/api/v1/finanzas/nomina",
        json={
            "sucursal_clave": BRANCH, "anio_iso": 2026, "semana_iso": week,
            "monto": amount, "nota": note, "actualizado_por": ACTOR,
        },
    )


def statement(week=33):
    response = client.get(
        "/api/v1/finanzas/estado-resultados",
        params={"anio_iso": 2026, "semana_iso": week, "sucursal_clave": BRANCH},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_manual_payroll_feeds_the_income_statement_as_fixed_expense():
    setup_branch()
    try:
        before = statement()
        assert Decimal(str(before["desglose_gastos"]["nomina"])) == Decimal("0")

        saved = save("12345.67", note="Semana completa")
        assert saved.status_code == 200, saved.text
        assert Decimal(str(saved.json()["capturado"])) == Decimal("12345.67")

        data = statement()
        assert Decimal(str(data["desglose_gastos"]["nomina"])) == Decimal("12345.67")
        assert Decimal(str(data["resumen"]["gastos_fijos"])) == Decimal("12345.67")
        assert Decimal(str(data["resumen"]["costos_variables"])) == Decimal("0")
        row = data["detalle_gastos"]["nomina"][0]
        assert row["tipo_documento"] == "nomina_manual" and row["pago"] == "Semana completa"

        # Otra semana no se ve afectada y la captura se puede corregir o borrar.
        assert Decimal(str(statement(32)["desglose_gastos"]["nomina"])) == Decimal("0")
        assert save("20000.00").status_code == 200
        assert Decimal(str(statement()["desglose_gastos"]["nomina"])) == Decimal("20000.00")
        cleared = save(None)
        assert cleared.status_code == 200 and cleared.json()["capturado"] is None
        assert Decimal(str(statement()["desglose_gastos"]["nomina"])) == Decimal("0")
    finally:
        cleanup()


def test_payroll_overview_lists_captured_and_validates_input():
    setup_branch()
    try:
        assert save("100.00").status_code == 200
        overview = client.get(
            "/api/v1/finanzas/nomina",
            params={"anio_iso": 2026, "semana_iso": 33, "sucursal_clave": BRANCH},
        )
        assert overview.status_code == 200, overview.text
        assert Decimal(str(overview.json()[0]["capturado"])) == Decimal("100.00")
        assert save("-1").status_code == 422
        assert save("100.00", week=54).status_code == 422
        bad_branch = client.post(
            "/api/v1/finanzas/nomina",
            json={"sucursal_clave": "NO-EXISTE", "anio_iso": 2026, "semana_iso": 33, "monto": "1", "actualizado_por": ACTOR},
        )
        assert bad_branch.status_code == 422
    finally:
        cleanup()
