import os

# Las pruebas no deben lanzar procesos lectores reales al encolar documentos.
os.environ.setdefault("FACTURAS_OCR_AUTOSTART_WORKERS", "false")
# El valor por defecto de la app es "seguro" (D-028). La mayoría de las pruebas ejercen
# las rutas de datos sin sesión; las de modo seguro lo activan en su propia fixture.
os.environ.setdefault("FACTURAS_ACCESO_MODO", "abierto")
