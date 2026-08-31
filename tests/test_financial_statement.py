from decimal import Decimal
from io import BytesIO

import psycopg
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.config import get_settings
from app.main import app
from app.accounting import _estimated_sales_commissions
from app.financial_reports import month_iso_periods


ACTOR = "pytest-finance"
SUBCATEGORY_KEY = "PYTEST_FINANCE"
COST_CENTER_KEY = "PYTEST_AREA"


def test_monthly_report_uses_iso_weeks_with_at_least_four_days_in_month():
    assert month_iso_periods(2026, 8) == [(2026, 32), (2026, 33), (2026, 34), (2026, 35)]
    assert month_iso_periods(2027, 1) == [(2027, 1), (2027, 2), (2027, 3), (2027, 4)]


def test_financial_report_options_expose_periods_sections_and_operating_branches():
    response = TestClient(app).get("/api/v1/reportes-financieros/opciones")
    assert response.status_code == 200, response.text
    data = response.json()
    assert {"resumen", "alimentos", "bebidas", "nomina", "movimientos"} <= {
        item["clave"] for item in data["secciones"]
    }
    assert {"DEMO-A", "DEMO-C", "DEMO-B"} <= {
        item["clave"] for item in data["sucursales"]
    }
    assert "POR-ASIGNAR" not in {item["clave"] for item in data["sucursales"]}


def test_monthly_financial_report_has_comparison_and_complete_decision_sections():
    response = TestClient(app).get(
        "/api/v1/reportes-financieros/reporte.pdf",
        params={"modo": "mensual", "anio": 2026, "mes": 8},
    )
    assert response.status_code == 200, response.text
    assert "reporte-financiero-2026-08-consolidado.pdf" in response.headers["content-disposition"]
    reader = PdfReader(BytesIO(response.content))
    assert len(reader.pages) >= 4
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    for label in (
        "Agosto 2026", "COMPARACION CONTRA JULIO 2026",
        "ESTADO DE RESULTADOS DEL PERIODO", "ALIMENTOS - VENTA Y COMPRAS",
        "BEBIDAS - VENTA Y COMPRAS", "NOMINA Y PRODUCTIVIDAD",
        "PUNTO DE EQUILIBRIO Y SEGURIDAD", "COMPARATIVO POR SUCURSAL",
        "PRINCIPALES MOVIMIENTOS DE GASTO",
    ):
        assert label in text


def test_configurable_financial_report_only_includes_selected_blocks():
    response = TestClient(app).get(
        "/api/v1/reportes-financieros/reporte.pdf",
        params={
            "modo": "semanas", "anio": 2026, "semanas": "32,33",
            "sucursal_clave": "DEMO-C", "secciones": "nomina",
        },
    )
    assert response.status_code == 200, response.text
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(response.content)).pages)
    assert "NOMINA Y PRODUCTIVIDAD" in text
    assert "VENTAS POR CANAL Y FAMILIA" not in text
    assert "ALIMENTOS - VENTA Y COMPRAS" not in text
    assert "COMPOSICION DE GASTOS" not in text


def test_weekly_purchase_report_is_one_page_a4_without_history_or_document_detail():
    response = TestClient(app).get(
        "/api/v1/finanzas/reporte-compras.pdf",
        params={"anio_iso": 2026, "semana_iso": 32},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert "reporte-compras-2026-s32-consolidado.pdf" in response.headers["content-disposition"]
    reader = PdfReader(BytesIO(response.content))
    assert len(reader.pages) == 1
    assert float(reader.pages[0].mediabox.width) == pytest.approx(595.28, abs=0.1)
    assert float(reader.pages[0].mediabox.height) == pytest.approx(841.89, abs=0.1)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "COMPOSICION DE COMPRAS" in text
    assert "LECTURA DE LA SEMANA" in text
    assert "PROVEEDORES CON MAYOR COMPRA" in text
    assert "TENDENCIA HISTORICA" in text
    assert "Proveedores activos" not in text
    assert "DOCUMENTOS" not in text
    assert "Semana anterior" not in text
    assert "Promedio 4 semanas" not in text
    assert "Desglose por sucursal" not in text
    assert "Detalle documental" not in text


def test_weekly_executive_report_is_one_page_a4_with_six_key_indicators():
    response = TestClient(app).get(
        "/api/v1/finanzas/reporte-ejecutivo.pdf",
        params={"anio_iso": 2026, "semana_iso": 30, "sucursal_clave": "DEMO-A"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert "reporte-financiero-2026-s30-demo-a.pdf" in response.headers["content-disposition"]
    reader = PdfReader(BytesIO(response.content))
    assert len(reader.pages) == 1
    assert float(reader.pages[0].mediabox.width) == pytest.approx(595.28, abs=0.1)
    assert float(reader.pages[0].mediabox.height) == pytest.approx(841.89, abs=0.1)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    for label in (
        "Margen operativo", "Compras alimentos y bebidas", "Mano de obra",
        "Ticket promedio", "Punto de equilibrio", "Margen de seguridad",
    ):
        assert label in text
    assert "Semana anterior" not in text
    assert "Comparativo por unidad" not in text
    assert "Nota metodologica" not in text
    assert "COMPOSICION OPERATIVA" in text
    assert "PROVISIONES FIJAS INCLUIDAS" not in text


def test_blank_executive_report_has_explanations_without_financial_values():
    response = TestClient(app).get("/api/v1/finanzas/reporte-ejecutivo-vacio.pdf")
    assert response.status_code == 200, response.text
    assert "plantilla-reporte-financiero-consolidado.pdf" in response.headers["content-disposition"]
    reader = PdfReader(BytesIO(response.content))
    assert len(reader.pages) == 3
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "PLANTILLA VACIA" in text
    assert "Por capturar" in text
    assert "Por calcular" in text
    assert "Mide cuanto queda de cada peso vendido" in text
    assert "$" not in text


def cleanup_catalog_test_data():
    with psycopg.connect(get_settings().database_url) as conn:
        ids = conn.execute(
            """
            SELECT id FROM catalog.subcategorias WHERE clave = %s
            UNION ALL
            SELECT id FROM catalog.centros_costo WHERE clave = %s
            """,
            (SUBCATEGORY_KEY, COST_CENTER_KEY),
        ).fetchall()
        for (item_id,) in ids:
            conn.execute("DELETE FROM audit.cambios_catalogo WHERE entidad_id = %s", (item_id,))
        conn.execute("DELETE FROM catalog.subcategorias WHERE clave = %s", (SUBCATEGORY_KEY,))
        conn.execute("DELETE FROM catalog.centros_costo WHERE clave = %s", (COST_CENTER_KEY,))
        conn.execute("DELETE FROM finance.ventas WHERE registrada_por = %s", (ACTOR,))


def test_weekly_income_statement_uses_synthetic_sales_fixture():
    client = TestClient(app)
    response = client.get(
        "/api/v1/finanzas/estado-resultados",
        params={"anio_iso": 2026, "semana_iso": 30, "sucursal_clave": "DEMO-A"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    summary = data["resumen"]
    assert Decimal(str(summary["ventas"])) == Decimal("172000")
    assert summary["ventas_demo"] is True
    assert len(data["sucursales"]) == 1
    indicators = data["indicadores_restaurante"]
    assert indicators["metodologia_costos"] == "compras_aplicadas_sin_ajuste_inventario"
    assert Decimal(str(indicators["ticket_promedio"])) > 0


def test_estimated_sales_commissions_use_credit_and_app_rules():
    demo_a = _estimated_sales_commissions({
        "sucursal_clave": "DEMO-A", "visa": "1000", "amex": "500",
        "uber": "100", "rappi": "200",
    })
    assert [(item["concepto"], item["monto"]) for item in demo_a] == [
        ("TERMINALES VISA", Decimal("26.00")),
        ("TERMINALES AMEX", Decimal("19.00")),
        ("COMISION BANCO", Decimal("33.00")),
        ("COMISIONES APLICACIONES", Decimal("31.00")),
        ("COMISIONES APLICACIONES", Decimal("72.00")),
    ]
    demo_c = _estimated_sales_commissions({
        "sucursal_clave": "DEMO-C", "visa": "1000", "amex": "500",
        "uber": "100", "rappi": "200",
    })
    assert {item["concepto"] for item in demo_c} == {
        "TERMINALES VISA", "TERMINALES AMEX", "COMISION BANCO",
    }


def test_fixed_provisions_are_itemized_and_feed_labor_indicator():
    response = TestClient(app).get(
        "/api/v1/finanzas/estado-resultados",
        params={"anio_iso": 2026, "semana_iso": 30, "sucursal_clave": "DEMO-A"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    fixed = data["detalle_gastos"]["fijos"]
    payroll = data["detalle_gastos"]["nomina"]
    assert {row["proveedor"] for row in fixed} == {
        "Renta", "Agua y drenaje", "C.F.E.", "Fumigacion",
        "Sistema de punto de venta", "Servicio operativo",
    }
    assert [(row["proveedor"], Decimal(str(row["monto_aplicado"]))) for row in payroll] == [
        ("Nomina", Decimal("30000.00")),
    ]
    assert Decimal(str(data["indicadores_restaurante"]["mano_obra"])) == Decimal("30000.00")
    assert Decimal(str(data["resumen"]["gastos_fijos"])) == Decimal("64742.74")


def test_income_statement_can_filter_one_branch():
    response = TestClient(app).get(
        "/api/v1/finanzas/estado-resultados",
        params={"anio_iso": 2026, "semana_iso": 30, "sucursal_clave": "DEMO-A"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["sucursales"]) == 1
    assert data["sucursales"][0]["sucursal_clave"] == "DEMO-A"
    assert Decimal(str(data["resumen"]["ventas"])) == Decimal("172000")


def test_expense_detail_reconciles_with_statement_sections():
    response = TestClient(app).get(
        "/api/v1/finanzas/estado-resultados",
        params={"anio_iso": 2026, "semana_iso": 32},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    detail = data["detalle_gastos"]
    assert detail
    for group, rows in detail.items():
        applied = sum((Decimal(str(row["monto_aplicado"])) for row in rows), Decimal("0"))
        assert applied == Decimal(str(data["desglose_gastos"][group]))
        assert all(row["proveedor"] and row["fecha"] and row["folio"] for row in rows)
        assert all(row["semana_aplicacion"] == 32 for row in rows)


def test_accounting_subcategories_and_cost_centers_are_configurable():
    cleanup_catalog_test_data()
    client = TestClient(app)
    try:
        catalogs = client.get("/api/v1/catalogos/contables")
        assert catalogs.status_code == 200, catalogs.text
        variables_id = next(
            item["id"] for item in catalogs.json()["categorias"] if item["clave"] == "VARIABLES"
        )
        created_subcategory = client.post(
            "/api/v1/catalogos/subcategorias",
            json={
                "categoria_id": variables_id,
                "clave": SUBCATEGORY_KEY,
                "nombre": "Prueba financiera",
                "actualizado_por": ACTOR,
            },
        )
        assert created_subcategory.status_code == 200, created_subcategory.text
        subcategory_id = created_subcategory.json()["id"]
        deactivated = client.post(
            "/api/v1/catalogos/subcategorias",
            json={
                "id": subcategory_id,
                "categoria_id": variables_id,
                "clave": SUBCATEGORY_KEY,
                "nombre": "Prueba financiera actualizada",
                "activa": False,
                "actualizado_por": ACTOR,
            },
        )
        assert deactivated.status_code == 200, deactivated.text
        assert deactivated.json()["activa"] is False

        created_center = client.post(
            "/api/v1/catalogos/centros-costo",
            json={
                "clave": COST_CENTER_KEY,
                "nombre": "Área de prueba",
                "actualizado_por": ACTOR,
            },
        )
        assert created_center.status_code == 200, created_center.text
        assert created_center.json()["activo"] is True

        with psycopg.connect(get_settings().database_url) as conn:
            audit_count = conn.execute(
                "SELECT count(*) FROM audit.cambios_catalogo WHERE realizado_por = %s",
                (ACTOR,),
            ).fetchone()[0]
            assert audit_count == 3
    finally:
        cleanup_catalog_test_data()


def test_week_30_sales_breakdown_matches_synthetic_daily_fixture():
    response = TestClient(app).get(
        "/api/v1/finanzas/ventas-desglose",
        params={"anio_iso": 2026, "semana_iso": 30, "sucursal_clave": "DEMO-A"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["editable"] is True
    assert len(data["filas"]) == 7
    totals = data["totales"]
    assert Decimal(str(totals["efectivo"])) == Decimal("42500.00")
    assert Decimal(str(totals["rappi"])) == Decimal("6000.00")
    assert Decimal(str(totals["uber"])) == Decimal("4000.00")
    assert Decimal(str(totals["visa"])) == Decimal("108000.00")
    assert Decimal(str(totals["amex"])) == Decimal("11500.00")
    assert Decimal(str(totals["monto_neto"])) == Decimal("172000.00")
    assert Decimal(str(totals["total_mix"])) == Decimal("172000.00")
    assert Decimal(str(totals["diferencia_desglose"])) == Decimal("0")


def test_consolidated_sales_breakdown_is_sum_of_all_branches():
    client = TestClient(app)
    consolidated = client.get(
        "/api/v1/finanzas/ventas-desglose",
        params={"anio_iso": 2026, "semana_iso": 30},
    )
    assert consolidated.status_code == 200, consolidated.text
    data = consolidated.json()
    assert data["editable"] is False
    assert data["alcance"]["tipo"] == "consolidado"
    assert len(data["filas"]) == 7

    catalogs = client.get("/api/v1/catalogos").json()
    expected = Decimal("0")
    for branch in catalogs["sucursales"]:
        if branch["clave"] == "POR-ASIGNAR" or not branch.get("activa", True):
            continue
        response = client.get(
            "/api/v1/finanzas/ventas-desglose",
            params={"anio_iso": 2026, "semana_iso": 30, "sucursal_clave": branch["clave"]},
        )
        if response.status_code == 200:
            expected += Decimal(str(response.json()["totales"]["monto_neto"]))
    assert Decimal(str(data["totales"]["monto_neto"])) == expected


def test_daily_sales_breakdown_can_be_edited_and_recalculates_net_sales():
    cleanup_catalog_test_data()
    client = TestClient(app)
    try:
        catalogs = client.get("/api/v1/catalogos").json()
        branch_id = next(item["id"] for item in catalogs["sucursales"] if item["clave"] == "DEMO-A")
        saved = client.post(
            "/api/v1/finanzas/ventas-desglose",
            json={
                "sucursal_id": branch_id,
                "actualizada_por": ACTOR,
                "filas": [{
                    "fecha": "2026-07-27",
                    "efectivo": "1000.00",
                    "dolares": "10.00",
                    "tipo_cambio": "20.00",
                    "rappi": "100.00",
                    "uber": "50.00",
                    "visa": "500.00",
                    "amex": "150.00",
                    "venta_otro": "100.00",
                    "venta_aplicaciones": "150.00",
                    "venta_alimentos": "1200.00",
                    "venta_bebidas": "550.00",
                    "visitas": 4,
                }],
            },
        )
        assert saved.status_code == 200, saved.text
        detail = client.get(
            "/api/v1/finanzas/ventas-desglose",
            params={"anio_iso": 2026, "semana_iso": 31, "sucursal_clave": "DEMO-A"},
        )
        assert detail.status_code == 200, detail.text
        row = detail.json()["filas"][0]
        assert Decimal(str(row["conversion_usd"])) == Decimal("200")
        assert Decimal(str(row["credito"])) == Decimal("650")
        assert Decimal(str(row["monto_neto"])) == Decimal("2000")
        assert Decimal(str(row["ticket_promedio"])) == Decimal("500")
    finally:
        cleanup_catalog_test_data()
