from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reportlab.lib import colors


BRAND_DIR = Path(__file__).resolve().parent / "static" / "brands"


@dataclass(frozen=True)
class ReportBrand:
    key: str
    name: str
    primary: colors.Color
    secondary: colors.Color
    pale: colors.Color
    logo_path: Path | None


BRANDS = {
    "DEMO-A": ReportBrand(
        key="DEMO-A",
        name="Restaurante Demo Uno",
        primary=colors.HexColor("#000455"),
        secondary=colors.HexColor("#34387E"),
        pale=colors.HexColor("#EEF0F8"),
        logo_path=None,
    ),
    "DEMO-C": ReportBrand(
        key="DEMO-C",
        name="Restaurante Demo Tres",
        primary=colors.HexColor("#EE2A3B"),
        secondary=colors.HexColor("#8F1F2B"),
        pale=colors.HexColor("#FCECEE"),
        logo_path=None,
    ),
    "DEMO-B": ReportBrand(
        key="DEMO-B",
        name="Restaurante Demo Dos",
        primary=colors.HexColor("#EC1C23"),
        secondary=colors.HexColor("#111111"),
        pale=colors.HexColor("#FCE7C1"),
        logo_path=None,
    ),
}

CONSOLIDATED = ReportBrand(
    key="CONSOLIDADO",
    name="Grupo restaurantero",
    primary=colors.HexColor("#24352D"),
    secondary=colors.HexColor("#56665E"),
    pale=colors.HexColor("#EEF2EF"),
    logo_path=None,
)


def get_report_brand(branch_key: str | None) -> ReportBrand:
    return BRANDS.get((branch_key or "").upper(), CONSOLIDATED)


def available_logos(branch_key: str | None) -> list[Path]:
    brand = get_report_brand(branch_key)
    if brand.logo_path and brand.logo_path.exists():
        return [brand.logo_path]
    return [item.logo_path for item in BRANDS.values() if item.logo_path and item.logo_path.exists()]
