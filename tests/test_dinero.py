"""Dinero sin `float`: el reparto de periodos conserva el total al centavo y el redondeo es el del negocio."""
import random
from datetime import date
from decimal import Decimal

import pytest

from app.periodification import allocate_period
from app.receipt_pdf import money_text

CENTAVO = Decimal("0.01")


def test_el_reparto_conserva_el_total_exacto_en_muchos_casos():
    azar = random.Random(20261019)
    periodos = [
        ("mensual", date(2026, 8, 1), date(2026, 8, 31)),       # 4 semanas
        ("mensual", date(2026, 2, 1), date(2026, 2, 28)),       # 4 semanas
        ("bimestral", date(2026, 7, 1), date(2026, 8, 31)),     # ~9 semanas
        ("personalizado", date(2026, 1, 5), date(2026, 3, 29)),  # ~12 semanas
    ]
    for _ in range(300):
        total = Decimal(azar.randint(1, 10**9)) / 100
        tipo, desde, hasta = azar.choice(periodos)
        partes = allocate_period(total, tipo, desde, hasta)
        montos = [p["monto"] for p in partes]
        assert sum(montos) == total, (total, tipo)
        assert all(m == m.quantize(CENTAVO) and m >= 0 for m in montos)
        # Todas iguales salvo la última, que absorbe el residuo (< 1 centavo por semana).
        assert len(set(montos[:-1])) <= 1
        assert 0 <= montos[-1] - montos[0] < CENTAVO * len(montos)


def test_un_tercio_de_100_deja_el_centavo_en_la_ultima_semana():
    partes = allocate_period(Decimal("100.00"), "personalizado", date(2026, 8, 3), date(2026, 8, 23))
    assert [p["monto"] for p in partes] == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]


def test_el_total_con_mas_decimales_se_redondea_a_centavos_antes_de_repartir():
    partes = allocate_period(Decimal("10.005"), "personalizado", date(2026, 8, 3), date(2026, 8, 9))
    assert sum(p["monto"] for p in partes) == Decimal("10.00") or sum(p["monto"] for p in partes) == Decimal("10.01")


@pytest.mark.parametrize(
    "valor, esperado",
    [
        (Decimal("0.005"), "0.01"),            # mitad hacia arriba, no al par
        (Decimal("2.675"), "2.68"),            # con float daría 2.67
        (Decimal("1234567.895"), "1,234,567.90"),
        (Decimal("99999999999999.99"), "99,999,999,999,999.99"),  # tope de numeric(14,2) sin perder centavos
        ("1500", "1,500.00"),
        (Decimal("0"), "0.00"),
    ],
)
def test_el_importe_del_pdf_se_redondea_como_el_negocio_y_no_pierde_centavos(valor, esperado):
    assert money_text(valor) == esperado
