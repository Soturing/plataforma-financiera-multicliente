from datetime import date
from decimal import Decimal

import pytest

from app.errors import DomainError
from app.main import _validate_analytics_filters
from app.repository import _filter_analytics_rows


ROWS = [
    {
        "movimiento_id": "a",
        "fecha": date(2026, 8, 10),
        "categoria": "Restaurante",
        "total": Decimal("100.00"),
    },
    {
        "movimiento_id": "b",
        "fecha": date(2026, 8, 7),
        "categoria": "Fijos",
        "total": Decimal("200.00"),
    },
    {
        "movimiento_id": "c",
        "fecha": date(2026, 8, 5),
        "categoria": "Variables",
        "total": Decimal("300.00"),
    },
]


def test_filters_by_iso_week_and_category():
    assert [row["movimiento_id"] for row in _filter_analytics_rows(
        ROWS, anio_iso=2026, semana_iso=33, categoria="RESTAURANTE"
    )] == ["a"]
    assert [row["movimiento_id"] for row in _filter_analytics_rows(
        ROWS, anio_iso=2026, semana_iso=32
    )] == ["b", "c"]


def test_filters_by_inclusive_date_range():
    result = _filter_analytics_rows(
        ROWS, fecha_desde=date(2026, 8, 5), fecha_hasta=date(2026, 8, 7)
    )
    assert [row["movimiento_id"] for row in result] == ["b", "c"]


def test_rejects_mixed_or_incomplete_periods():
    with pytest.raises(DomainError):
        _validate_analytics_filters(2026, None, None, None, None)
    with pytest.raises(DomainError):
        _validate_analytics_filters(
            2026, 33, date(2026, 8, 1), date(2026, 8, 10), None
        )
    with pytest.raises(DomainError):
        _validate_analytics_filters(None, None, date(2026, 8, 10), date(2026, 8, 1), None)
