from io import BytesIO
from textwrap import wrap
from typing import Any

import fitz


def _safe(value: Any, fallback: str = "—") -> str:
    text = str(value).strip() if value is not None else ""
    return text or fallback


def render_receipt_pdf(receipt: dict[str, Any]) -> bytes:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    green = (0.09, 0.42, 0.27)
    dark = (0.09, 0.13, 0.11)
    muted = (0.39, 0.45, 0.42)
    amber = (0.91, 0.72, 0.29)

    page.draw_rect(fitz.Rect(0, 0, 595, 105), color=green, fill=green)
    page.insert_text((42, 46), "COMPROBANTE INTERNO", fontsize=21, fontname="hebo", color=(1, 1, 1))
    page.insert_text((42, 72), f"Número: {_safe(receipt['numero_documento'])}", fontsize=12, fontname="helv", color=(1, 1, 1))
    page.draw_rect(fitz.Rect(390, 32, 550, 74), color=amber, fill=amber)
    page.insert_textbox(
        fitz.Rect(400, 43, 540, 69), "SIN CFDI · NO DEDUCIBLE",
        fontsize=9, fontname="hebo", align=fitz.TEXT_ALIGN_CENTER, color=dark,
    )

    fields = [
        ("Folio interno", receipt["folio"]),
        ("Fecha del gasto", receipt["fecha_gasto"]),
        ("Proveedor", receipt["proveedor"]),
        ("Teléfono", receipt.get("proveedor_telefono")),
        ("Forma de pago", str(receipt["metodo_pago"]).capitalize()),
        ("Restaurante / sucursal", f"{receipt['restaurante']} · {receipt['sucursal']}"),
        ("Clasificación", f"{receipt['categoria']} · {_safe(receipt.get('subcategoria'), 'Sin subcategoría')}"),
        ("Creado por", f"{receipt['creado_por']} ({receipt['rol_creador']})"),
    ]
    y = 137
    for label, value in fields:
        page.insert_text((42, y), label.upper(), fontsize=7.5, fontname="hebo", color=muted)
        page.insert_textbox(
            fitz.Rect(190, y - 11, 550, y + 14), _safe(value), fontsize=10.5,
            fontname="helv", color=dark,
        )
        page.draw_line(fitz.Point(42, y + 16), fitz.Point(550, y + 16), color=(0.88, 0.90, 0.89))
        y += 39

    y += 6
    page.insert_text((42, y), "CONCEPTO", fontsize=8, fontname="hebo", color=muted)
    concept = "\n".join(wrap(_safe(receipt["concepto"]), 85))
    page.insert_textbox(fitz.Rect(42, y + 12, 550, y + 75), concept, fontsize=11, fontname="helv", color=dark)
    y += 92

    page.draw_rect(fitz.Rect(330, y, 550, y + 58), color=green, fill=(0.91, 0.95, 0.93))
    page.insert_text((346, y + 21), "TOTAL", fontsize=9, fontname="hebo", color=green)
    page.insert_textbox(
        fitz.Rect(390, y + 12, 535, y + 44), f"$ {receipt['total']:,.2f} MXN",
        fontsize=17, fontname="hebo", align=fitz.TEXT_ALIGN_RIGHT, color=dark,
    )

    if len(receipt["distribuciones"]) > 1:
        y += 82
        page.insert_text((42, y), "DISTRIBUCIÓN DEL GASTO", fontsize=8, fontname="hebo", color=muted)
        for item in receipt["distribuciones"]:
            y += 20
            page.insert_text((52, y), f"{item['restaurante']} · {item['sucursal']}", fontsize=9, color=dark)
            page.insert_textbox(
                fitz.Rect(390, y - 11, 540, y + 7), f"$ {float(item['monto']):,.2f}",
                fontsize=9, align=fitz.TEXT_ALIGN_RIGHT, color=dark,
            )

    signature_y = 700
    page.draw_line(fitz.Point(42, signature_y), fitz.Point(255, signature_y), color=dark)
    page.draw_line(fitz.Point(340, signature_y), fitz.Point(553, signature_y), color=dark)
    page.insert_textbox(
        fitz.Rect(42, signature_y + 7, 255, signature_y + 36),
        f"Proveedor: {_safe(receipt.get('firma_proveedor_nombre'), 'No requerida')}",
        fontsize=8, align=fitz.TEXT_ALIGN_CENTER, color=muted,
    )
    approvals = receipt.get("primera_aprobacion_por") or "Pendiente"
    page.insert_textbox(
        fitz.Rect(340, signature_y + 7, 553, signature_y + 36), f"Autorización: {approvals}",
        fontsize=8, align=fitz.TEXT_ALIGN_CENTER, color=muted,
    )
    page.insert_textbox(
        fitz.Rect(42, 774, 553, 815),
        "Documento de control interno. No sustituye un CFDI ni acredita por sí mismo deducibilidad fiscal o IVA.",
        fontsize=8, align=fitz.TEXT_ALIGN_CENTER, color=muted,
    )

    output = BytesIO()
    document.save(output, garbage=4, deflate=True)
    document.close()
    return output.getvalue()
