"""Contenido mínimo con firma válida para las pruebas que suben archivos falsos (§3.6.4)."""

# Firma JPEG (SOI + APP0). Lo que sigue lo pone cada prueba; el lector sólo mira los primeros bytes.
JPEG = b"\xff\xd8\xff\xe0"
