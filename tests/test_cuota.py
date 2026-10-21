import asyncio
import io

import pytest
from starlette.datastructures import Headers, UploadFile

from app import cuota
from app.config import Settings
from app.errors import DomainError
from app.storage import save_upload


def _pdf(tamano: int) -> bytes:
    return b"%PDF-1.4\n" + b"0" * (tamano - 9)


def _ajustes(tmp_path, **extra):
    return Settings(database_url="postgresql://u:p@127.0.0.1:1/x", upload_dir=tmp_path / "subidas",
                    cuota_documentos_dia=0, cuota_almacenamiento_mb=0, antivirus_modo="apagado", _env_file=None, **extra)


def _subir(ajustes, tamano=1000):
    archivo = UploadFile(file=io.BytesIO(_pdf(tamano)), filename="f.pdf", headers=Headers({"content-type": "application/pdf"}))
    return asyncio.run(save_upload(archivo, ajustes))


@pytest.fixture(autouse=True)
def limpio():
    cuota.reiniciar()
    yield
    cuota.reiniciar()


def test_el_tope_diario_de_documentos_rechaza_con_429_al_pasarse(tmp_path):
    ajustes = Settings(
        database_url="postgresql://u:p@127.0.0.1:1/x", upload_dir=tmp_path / "subidas", cuota_documentos_dia=2,
        cuota_almacenamiento_mb=0, antivirus_modo="apagado", _env_file=None)
    _subir(ajustes)
    _subir(ajustes)
    with pytest.raises(DomainError) as error:
        _subir(ajustes)
    assert error.value.status_code == 429 and "límite diario" in error.value.message


def test_la_cuota_de_almacenamiento_rechaza_con_507_y_no_deja_el_archivo(tmp_path):
    ajustes = Settings(database_url="postgresql://u:p@127.0.0.1:1/x", upload_dir=tmp_path / "subidas",
                       cuota_documentos_dia=0, cuota_almacenamiento_mb=1, antivirus_modo="apagado", _env_file=None)
    primero, _, _ = _subir(ajustes, 600_000)
    with pytest.raises(DomainError) as error:
        _subir(ajustes, 600_000)
    assert error.value.status_code == 507
    assert [p.name for p in (tmp_path / "subidas").iterdir()] == [primero.name]


def test_con_cuota_en_cero_no_hay_tope(tmp_path):
    ajustes = _ajustes(tmp_path)
    for _ in range(5):
        _subir(ajustes, 2000)


def test_el_aviso_al_80_por_ciento_se_registra_una_vez(tmp_path, caplog):
    ajustes = Settings(database_url="postgresql://u:p@127.0.0.1:1/x", upload_dir=tmp_path / "subidas",
                       cuota_documentos_dia=0, cuota_almacenamiento_mb=1, antivirus_modo="apagado", _env_file=None)
    _subir(ajustes, 850_000)
    _subir(ajustes, 10_000)
    avisos = [r for r in caplog.records if "% de la cuota" in r.getMessage()]
    assert len(avisos) == 1
