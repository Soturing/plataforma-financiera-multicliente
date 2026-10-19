import os

# Las pruebas no deben lanzar procesos lectores reales al encolar documentos.
os.environ.setdefault("FACTURAS_OCR_AUTOSTART_WORKERS", "false")
# Sin límite de peticiones en la suite (todas las pruebas comparten una IP); las pruebas del
# límite lo activan en su propia fixture.
os.environ.setdefault("FACTURAS_LIMITE_PETICIONES_POR_MINUTO", "0")
os.environ.setdefault("FACTURAS_LIMITE_ACCESO_POR_MINUTO", "0")
# El valor por defecto de la app es "seguro" (D-028). La mayoría de las pruebas ejercen
# las rutas de datos sin sesión; las de modo seguro lo activan en su propia fixture.
os.environ.setdefault("FACTURAS_ACCESO_MODO", "abierto")
