"""Endurecimiento de respuestas (roadmap §3.6, hallazgos 6, 7 y 14 de la auditoría).

Cabeceras de seguridad, disposición de archivos subidos y apagado de la documentación
interactiva fuera de desarrollo. Las cabeceras de TLS y de proxy viven en
`deploy/servidor/Caddyfile`; aquí va lo que la propia aplicación debe fijar.
"""

# Sólo estos tipos se muestran en el navegador. Lo demás se descarga, para que un
# archivo subido nunca se ejecute como página en nuestro origen.
TIPOS_EN_LINEA = frozenset({"application/pdf", "image/jpeg", "image/png", "image/webp"})

# Página y scripts sólo del propio origen. `style-src` admite `unsafe-inline` porque la
# interfaz genera atributos `style` al pintar; quitarlo es una tarea de §3.6.9 (innerHTML).
CONTENIDO_SEGURIDAD = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; frame-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'"
)

CABECERAS_SEGURIDAD = {
    "Content-Security-Policy": CONTENIDO_SEGURIDAD,
    "X-Content-Type-Options": "nosniff",
    # SAMEORIGIN: la pantalla de factura incrusta su propio archivo en un <iframe>.
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def disposicion(tipo_mime: str) -> str:
    """`inline` sólo para PDF e imágenes; el resto se descarga."""
    return "inline" if tipo_mime in TIPOS_EN_LINEA else "attachment"


def documentacion_activa(environment: str, acceso_modo: str) -> bool:
    """`/docs` y `/openapi.json` sólo en desarrollo con acceso abierto (§3.6.6)."""
    return environment != "produccion" and acceso_modo == "abierto"
