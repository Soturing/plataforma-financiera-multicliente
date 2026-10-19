"""Sube la versión (MAYOR.MENOR.PARCHE) y abre su sección en CHANGELOG.md.

Uso:
    python scripts/bump_version.py patch|minor|major [--dry-run]

No hace commit ni crea la etiqueta de git: imprime los comandos para hacerlo después de revisar.
"""

import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
CHANGELOG = ROOT / "CHANGELOG.md"
SECTION = "## [{version}] - {day}\n\n### Agregado\n\n- \n\n### Cambiado\n\n- \n\n### Corregido\n\n- \n\n"


def bump(current: str, part: str) -> str:
    major, minor, patch = (int(item) for item in current.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main(argv: list[str]) -> int:
    parts = [arg for arg in argv if not arg.startswith("--")]
    if len(parts) != 1 or parts[0] not in {"patch", "minor", "major"}:
        print(__doc__)
        return 2
    current = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", current):
        print(f"VERSION no tiene el formato MAYOR.MENOR.PARCHE: {current!r}")
        return 1
    new = bump(current, parts[0])
    print(f"{current} -> {new}")
    if "--dry-run" in argv:
        return 0
    VERSION_FILE.write_text(new + "\n", encoding="utf-8")
    text = CHANGELOG.read_text(encoding="utf-8")
    marker = re.search(r"^## \[", text, re.MULTILINE)
    section = SECTION.format(version=new, day=date.today().isoformat())
    text = text[: marker.start()] + section + text[marker.start():] if marker else text.rstrip() + "\n\n" + section
    CHANGELOG.write_text(text, encoding="utf-8")
    print("Complete CHANGELOG.md y luego:")
    print(f'  git add -A && git commit -m "chore: versión {new}" && git tag -a v{new} -m "Versión {new}"')
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
