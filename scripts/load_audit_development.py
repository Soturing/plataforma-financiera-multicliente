from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Carga el conjunto de desarrollo auditado.")
    parser.add_argument("sample_root", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--branch", default="DEMO-01")
    parser.add_argument("--actor", default="auditoria-demo")
    args = parser.parse_args()

    sample_root = args.sample_root.resolve()
    manifest = sample_root / "audit" / "clasificacion_visual.csv"
    source = sample_root / "source"
    rows = list(csv.DictReader(manifest.open(encoding="utf-8-sig")))
    selected = [row for row in rows if row["conjunto"] == "desarrollo"]
    streams = []
    files = []
    try:
        for row in selected:
            path = source / row["archivo"]
            stream = path.open("rb")
            streams.append(stream)
            files.append(("archivos", (path.name, stream, "application/pdf")))
        with httpx.Client(base_url=args.base_url, timeout=120) as client:
            response = client.post(
                "/api/v1/documentos/carga-masiva",
                data={"sucursal_clave": args.branch, "creada_por": args.actor},
                files=files,
            )
            response.raise_for_status()
            print(json.dumps(response.json(), ensure_ascii=False, indent=2, default=str))
    finally:
        for stream in streams:
            stream.close()


if __name__ == "__main__":
    main()
