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

## Razones sociales propias

El lector necesita saber cuáles son las razones sociales y RFC del grupo (los receptores) para no
confundirlos con el proveedor. Se toman del RFC y la razón social de cada sucursal y de la tabla
`catalog.entidades_propias` (migración 029; API `GET/POST /api/v1/entidades-propias`). Sin ellas el acierto
de proveedor baja de ~76 % a ~64 % en la Prueba 1; el RFC no cambia porque el QR y la posición bastan.

## Reproceso de un lote

`POST /api/v1/lotes/{id}/reprocesar` vuelve a leer los documentos no aprobados del lote con la lectura vigente
(crea nuevas versiones de OCR e interpretación; las anteriores se conservan). Cuidado: un catálogo de
proveedores creado por una lectura antigua (nombres o RFC erróneos, RFC del cliente como proveedor) contamina
la nueva lectura, porque el proveedor encontrado por RFC reemplaza el nombre propuesto; conviene depurarlo
antes de reprocesar.

## Páginas de una misma factura

Si en un lote dos páginas comparten **proveedor y folio detectado** y solo una trae total, la que no lo trae
se liga como *continuación* de la principal (`core.documentos_continuacion`, migración 031). La continuación
sale de la bandeja y la revisión muestra las páginas relacionadas del documento con un botón **Separar** que
la devuelve a la bandeja (lo separado a mano no se vuelve a ligar). Con totales en ambas páginas no se agrupa:
se trata como posible duplicado. El agrupado corre al guardar cada lectura (`app/page_groups.py`) y es
idempotente.

## Confianza por campo

Cada lectura guarda en `salida_json.confianza_campos` el nivel (`alta`, `media`, `baja`) y el motivo de cada
campo: **alta** cuando lo confirma una segunda fuente (QR del SAT, importe con letra, suma de subtotal e IVA,
RFC válido y repetido, etiqueta explícita); **baja** cuando es una suposición (folio inventado desde la
fecha, RFC con dígito verificador inválido, proveedor tomado del encabezado). En la Prueba 1 los campos
marcados `alta` acertaron 123 de 125 veces y los `baja` casi nunca. La pantalla de revisión resalta los
campos `baja` (rojo) y `media` (ámbar) y la bandeja muestra cuántos campos hay por revisar.
