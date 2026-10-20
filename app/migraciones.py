"""Aplicador único de migraciones (roadmap §3.7.3).

Lo usan el alta y la operación de clientes (`app.plataforma.tenants`), la base desechable del
CI (`scripts/preparar_base_pruebas.py`) y la base de desarrollo, de modo que todas lleven
el mismo registro (`public.migraciones_aplicadas`) y nadie dependa de montar archivos sueltos
en `initdb.d`.

    python -m app.migraciones aplicar --url postgresql://dueno:clave@127.0.0.1:5432/facturas_demo \\
        --semilla db/seeds/001_demo_catalogs.sql@010

Una base de desarrollo que ya tenía las migraciones por `initdb.d` se adopta sin repetirlas:
    python -m app.migraciones aplicar --url ... --hasta-previas 034
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

CARPETA = Path(__file__).resolve().parents[1] / "db" / "migrations"
TABLA = "public.migraciones_aplicadas"


def _numero(nombre: str) -> str:
    return nombre[:3]


def aplicar(
    url: str,
    *,
    carpeta: Path = CARPETA,
    hasta_previas: str | None = None,
    semillas: list[tuple[str, Path]] | None = None,
    tabla: str = TABLA,
) -> list[str]:
    """Aplica en orden, como propietaria, las migraciones que falten y las registra.

    `semillas` son pares (número de migración, archivo): se aplican justo después de esa
    migración, porque hay datos de demostración que deben existir antes de las siguientes
    (y antes de que RLS exista). `hasta_previas` marca como hechas las migraciones con ese
    número o menor sin ejecutarlas (adopción de una base ya migrada a mano).
    """
    archivos = sorted(carpeta.glob("*.sql"))
    semillas = semillas or []
    aplicadas: list[str] = []
    registro = sql.SQL(".").join(sql.Identifier(parte) for parte in tabla.split("."))
    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as c:
        c.execute(
            sql.SQL("CREATE TABLE IF NOT EXISTS {} (nombre text PRIMARY KEY, aplicada_en timestamptz NOT NULL DEFAULT now())").format(registro)
        )
        if hasta_previas:
            for a in archivos:
                if _numero(a.name) <= hasta_previas:
                    c.execute(sql.SQL("INSERT INTO {} (nombre) VALUES (%s) ON CONFLICT DO NOTHING").format(registro), (a.name,))
        hechas = {f["nombre"] for f in c.execute(sql.SQL("SELECT nombre FROM {}").format(registro)).fetchall()}

        def correr(nombre: str, archivo: Path) -> None:
            if nombre in hechas:
                return
            with c.transaction():
                c.execute(archivo.read_text(encoding="utf-8"))
                c.execute(sql.SQL("INSERT INTO {} (nombre) VALUES (%s)").format(registro), (nombre,))
            aplicadas.append(nombre)

        for a in archivos:
            correr(a.name, a)
            for numero, semilla in semillas:
                if numero == _numero(a.name):
                    correr(f"semilla:{semilla.name}", semilla)
    return aplicadas


def _semilla(valor: str) -> tuple[str, Path]:
    ruta, _, numero = valor.rpartition("@")
    if not ruta or len(numero) != 3 or not numero.isdigit():
        raise argparse.ArgumentTypeError("Use ARCHIVO@NNN (p. ej. db/seeds/001_demo_catalogs.sql@010)")
    return numero, Path(ruta)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aplica las migraciones pendientes a una base.")
    parser.add_argument("accion", choices=["aplicar"])
    parser.add_argument("--url", default=os.environ.get("FACTURAS_DATABASE_URL"), help="Conexión de la cuenta propietaria")
    parser.add_argument("--hasta-previas", help="Marca como aplicadas las migraciones hasta este número (NNN)")
    parser.add_argument("--semilla", action="append", default=[], type=_semilla, help="ARCHIVO@NNN: semilla tras esa migración")
    args = parser.parse_args(argv)
    if not args.url:
        parser.error("Falta --url (o FACTURAS_DATABASE_URL)")
    hechas = aplicar(args.url, hasta_previas=args.hasta_previas, semillas=args.semilla)
    print(f"Migraciones aplicadas: {len(hechas)}")
    for nombre in hechas:
        print(f"  {nombre}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
