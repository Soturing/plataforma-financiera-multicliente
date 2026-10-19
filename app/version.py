"""Versión del producto (MAYOR.MENOR.PARCHE); la fuente única es el archivo VERSION de la raíz."""

import re
from pathlib import Path

_FILE = Path(__file__).resolve().parents[1] / "VERSION"
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def read_version() -> str:
    try:
        value = _FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    return value if _SEMVER.match(value) else "0.0.0"


__version__ = read_version()
