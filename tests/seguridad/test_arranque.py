"""Arranque del contenedor de un cliente (fase 7): secretos de OpenBao y nada de credenciales a la app."""
from __future__ import annotations

import pytest

from app.plataforma import arranque, secretos


def test_url_interna_cambia_host_y_puerto_sin_tocar_credenciales():
    url = "postgresql://tenant_runtime:p%40ss@127.0.0.1:5440/facturas"
    assert arranque.url_interna(url, "db") == "postgresql://tenant_runtime:p%40ss@db:5432/facturas"
    assert arranque.url_interna(url, None) == url


def test_preparar_entorno_quita_la_credencial_y_agrega_secretos(monkeypatch):
    def falso(clave, role_id, secret_id):
        assert (clave, role_id, secret_id) == ("GRUPO-X", "rol", "secreto")
        return {
            "FACTURAS_DATABASE_URL": "postgresql://tenant_runtime:x@127.0.0.1:5442/facturas",
            "FACTURAS_CONTROL_DATABASE_URL": "postgresql://control_app:y@127.0.0.1:5436/facturas_control",
            "FACTURAS_OIDC_CLIENT_SECRET": "oidc",
        }

    monkeypatch.setattr(secretos, "secretos_arranque", falso)
    entorno = arranque.preparar_entorno({
        "FACTURAS_TENANT_CLAVE": "GRUPO-X", "SECRETOS_APP_ROLE_ID": "rol", "SECRETOS_APP_SECRET_ID": "secreto",
        "ARRANQUE_DB_HOST": "db", "ARRANQUE_CONTROL_DB_HOST": "control-postgres",
    })
    assert "SECRETOS_APP_ROLE_ID" not in entorno and "SECRETOS_APP_SECRET_ID" not in entorno
    assert entorno["FACTURAS_DATABASE_URL"].endswith("@db:5432/facturas")
    assert entorno["FACTURAS_CONTROL_DATABASE_URL"].endswith("@control-postgres:5432/facturas_control")
    assert entorno["FACTURAS_OIDC_CLIENT_SECRET"] == "oidc"


def test_sin_openbao_el_arranque_no_lanza_la_app(monkeypatch):
    def sellado(*_):
        raise secretos.SecretosError("sellado")

    monkeypatch.setattr(secretos, "secretos_arranque", sellado)
    monkeypatch.setattr(arranque.time, "sleep", lambda _: None)
    monkeypatch.setattr(arranque.os, "execvpe", lambda *a: pytest.fail("no debe arrancar sin secretos"))
    monkeypatch.setenv("FACTURAS_TENANT_CLAVE", "GRUPO-X")
    monkeypatch.setenv("SECRETOS_APP_ROLE_ID", "rol")
    monkeypatch.setenv("SECRETOS_APP_SECRET_ID", "secreto")
    assert arranque.main(["api"]) == 3
