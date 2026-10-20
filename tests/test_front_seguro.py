"""El front no debe volver a pintar texto de la base sin escapar ni a usar scripts o manejadores en línea.

Es una revisión estática y deliberadamente simple (roadmap §3.6.9): la CSP (`script-src 'self'`) frena los
scripts en línea, y `escapeHtml` cubre el texto que viene de la base o del usuario. Si esta prueba falla en una
interpolación legítima (un número o una constante), envuélvela igual en `escapeHtml(...)` o muévela a `textContent`.
"""
import re
from pathlib import Path

ESTATICOS = Path(__file__).resolve().parents[1] / "app" / "static"
APP_JS = (ESTATICOS / "app.js").read_text(encoding="utf-8")
INDEX = (ESTATICOS / "index.html").read_text(encoding="utf-8")

INTERPOLACION = re.compile(r"\$\{((?:[^{}]|\{[^{}]*\})*)\}")
# Campos que guardan texto escrito por personas o leído de documentos.
TEXTO_LIBRE = re.compile(
    r"\.(nombre|restaurante|proveedor|mensaje|detalle|message|folio|alias|rfc|nota|motivo|descripcion|razon|"
    r"archivo_nombre|proveedor_propuesto|nombre_normalizado|concepto_nombre)\b"
)


def test_el_texto_de_la_base_se_escapa_antes_de_ir_a_innerhtml():
    sin_escapar = []
    for numero, linea in enumerate(APP_JS.split("\n"), 1):
        if ".textContent" in linea:  # textContent no interpreta HTML
            continue
        for m in INTERPOLACION.finditer(linea):
            expresion = m.group(1)
            if TEXTO_LIBRE.search(expresion) and "escapeHtml(" not in expresion:
                sin_escapar.append(f"app.js:{numero}: ${{{expresion[:80]}}}")
    assert not sin_escapar, "Texto de la base sin escapeHtml:\n" + "\n".join(sin_escapar)


def test_no_hay_scripts_ni_manejadores_en_linea():
    """La CSP no permite `unsafe-inline` en scripts: un `onclick=` o un <script> en línea dejaría de funcionar."""
    assert not re.search(r"<script(?![^>]*\bsrc=)", INDEX), "index.html tiene un <script> en línea"
    assert not re.search(r"\son[a-z]+\s*=\s*[\"']", INDEX), "index.html tiene un manejador en línea"
    assert not re.search(r"\son[a-z]+\s*=\s*[\"']", APP_JS), "app.js genera un manejador en línea"
    assert "javascript:" not in INDEX and "javascript:" not in APP_JS


def test_el_helper_de_escape_cubre_los_cinco_caracteres():
    cuerpo = APP_JS[APP_JS.index("function escapeHtml"):][:400]
    for caracter in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
        assert caracter in cuerpo, f"escapeHtml no convierte a {caracter}"
