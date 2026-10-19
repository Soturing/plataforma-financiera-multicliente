import pytest
from pydantic import ValidationError

from app.config import Settings

URL = "postgresql://usuario:clave@127.0.0.1:5432/facturas"


def _ajustes(monkeypatch, **entorno):
    for nombre in ("FACTURAS_ACCESO_MODO", "FACTURAS_ENVIRONMENT"):
        monkeypatch.delenv(nombre, raising=False)
    for nombre, valor in entorno.items():
        monkeypatch.setenv(nombre, valor)
    return Settings(database_url=URL, _env_file=None)


def test_por_defecto_el_acceso_es_seguro(monkeypatch):
    assert _ajustes(monkeypatch).acceso_modo == "seguro"


def test_el_modo_abierto_sigue_disponible_en_desarrollo(monkeypatch):
    assert _ajustes(monkeypatch, FACTURAS_ACCESO_MODO="abierto").acceso_modo == "abierto"


def test_produccion_rechaza_el_modo_abierto(monkeypatch):
    with pytest.raises(ValidationError, match="seguro"):
        _ajustes(monkeypatch, FACTURAS_ENVIRONMENT="produccion", FACTURAS_ACCESO_MODO="abierto")


def test_produccion_con_modo_seguro_arranca(monkeypatch):
    ajustes = _ajustes(monkeypatch, FACTURAS_ENVIRONMENT="produccion")
    assert ajustes.acceso_modo == "seguro"
