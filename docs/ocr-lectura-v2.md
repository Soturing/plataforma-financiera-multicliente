# Lectura de facturas v2

Cambios derivados de la Prueba 1 (50 páginas reales de CamScanner; los documentos y la verdad terreno
viven fuera de git en `data/fixtures_ocr/`).

## Qué fallaba

- Los PDF de apps de escaneo traen una capa de texto propia, pobre o girada, que el sistema usaba sin
  verificar: el OCR de imagen casi nunca se ejecutaba.
- Las reglas de extracción tomaban al cliente como proveedor y su RFC como RFC del emisor, rellenaban el
  folio con la fecha, y elegían como total cualquier número cercano a la palabra "TOTAL".

## Flujo actual

1. **Escaneo:** si la mayoría de las páginas son una imagen que cubre ≥ 60 % de la hoja, se lee la imagen
   con PaddleOCR (con búsqueda de giro) aunque exista capa de texto (`HybridTextEngine._looks_scanned`).
2. **QR del SAT** (`app/qr_sat.py`, `zxing-cpp`): se lee en cada página de PDF o imagen y se guarda en
   `raw["qr_sat"]`. Aporta UUID, RFC del emisor y del receptor y total, sin depender del OCR. Es fuente
   prioritaria; solo ~60-70 % de las facturas lo traen legible.
3. **Extracción** (`app/extraction.py`), con contexto del grupo (`ocr_processing.reading_context`):
   RFC y nombres de las sucursales (receptores, nunca proveedor) y RFC de proveedores conocidos.
   - RFC: validación del dígito verificador y corrección de confusiones de OCR (`app/rfc.py`); se
     descartan RFC de PAC y los delimitados por `|` de la cadena original.
   - Proveedor: puntaje por sufijo legal, cercanía al RFC del emisor y posición en el encabezado.
   - Folio: etiquetas y formas conocidas (`FACTURA`, `Serie/Folio`, `NV`, `INV/…`, número suelto cercano a
     una etiqueta). Nunca fechas, años ni números de certificado; sin folio se conserva el respaldo
     DDMMYYYY con `folio_origen = "fecha"`.
   - Importes: se eligen con evidencia cruzada (importe con letra en `app/amount_words.py`, aritmética
     subtotal − descuento + IVA y presencia en el documento); las tasas "IVA 16 %" no son importes.
4. **Clasificación** (`app/classification.py`): tickets de caja, notas, remisiones y cotizaciones
   (nuevo tipo `cotizacion`, migración 028; no es gasto).

## Evaluación

`app/ocr_eval.py` compara contra la verdad terreno. `tests/test_ocr_regression.py` fija pisos de acierto
y se omite si no existe `data/fixtures_ocr/prueba1`.

| Campo | Antes | Con v2 (OCR de imagen + QR) |
|---|---|---|
| Proveedor | 42 % | 76 % |
| RFC del emisor | 14 % | 81 % |
| Folio | 10 % | 83 % |
| Fecha | 48 % | 76 % |
| Subtotal | 30 % | 70 % |
| IVA | 26 % | 77 % |
| Total | 32 % | 83 % |
| Tipo de documento | 58 % | 98 % |

Las reglas se ajustaron con esas mismas 50 páginas: la cifra es un piso de regresión, no una promesa de
acierto sobre documentos nuevos.

## Pendiente

- Remisiones y notas manuscritas: ningún OCR local las lee de forma fiable; siempre a revisión humana.
- Agrupar páginas de una misma factura (mismo folio) y alertar duplicados ticket + factura.
- Medir PaddleOCR medium en equipo con GPU (paquete aparte); en CPU de laptop no es viable.
