import os

# Las pruebas no deben lanzar procesos lectores reales al encolar documentos.
os.environ.setdefault("FACTURAS_OCR_AUTOSTART_WORKERS", "false")
