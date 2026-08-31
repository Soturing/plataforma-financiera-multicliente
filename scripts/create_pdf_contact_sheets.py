from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea hojas de contacto para auditar PDFs renderizados.")
    parser.add_argument("render_map", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--per-sheet", type=int, default=8)
    args = parser.parse_args()

    rows = list(csv.DictReader(args.render_map.open(encoding="utf-8-sig")))
    images: list[tuple[Path, str]] = []
    for row in rows:
        folder = Path(row["Folder"])
        for page_number, path in enumerate(sorted(folder.glob("*.jpg")), start=1):
            label = f'{int(row["Index"]):03d} - {row["File"]} - p.{page_number}'
            images.append((path, label))

    args.output.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default(size=18)
    columns = 2
    rows_per_sheet = math.ceil(args.per_sheet / columns)
    cell_width, cell_height = 900, 760
    label_height = 70

    for sheet_index, start in enumerate(range(0, len(images), args.per_sheet), start=1):
        canvas = Image.new("RGB", (columns * cell_width, rows_per_sheet * cell_height), "white")
        draw = ImageDraw.Draw(canvas)
        for position, (path, label) in enumerate(images[start : start + args.per_sheet]):
            column = position % columns
            row = position // columns
            x, y = column * cell_width, row * cell_height
            with Image.open(path) as original:
                thumbnail = ImageOps.contain(
                    original.convert("RGB"),
                    (cell_width - 30, cell_height - label_height - 20),
                )
            image_x = x + (cell_width - thumbnail.width) // 2
            image_y = y + label_height
            canvas.paste(thumbnail, (image_x, image_y))
            draw.multiline_text(
                (x + 15, y + 10), label, fill="black", font=font, spacing=3
            )
            draw.rectangle((x, y, x + cell_width - 1, y + cell_height - 1), outline="#777777", width=2)
        canvas.save(args.output / f"contacto_{sheet_index:02d}.jpg", quality=88)

    print(f"PAGES={len(images)}")
    print(f"SHEETS={math.ceil(len(images) / args.per_sheet)}")


if __name__ == "__main__":
    main()
