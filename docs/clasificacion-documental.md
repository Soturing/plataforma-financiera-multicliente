# Clasificación documental — v0.1

## Propósito

Determinar qué tipo de documento produjo el OCR antes de aplicar reglas de extracción contable. La clasificación no modifica ni descarta el texto original.

## Taxonomía inicial

- `factura_fiscal`
- `nota_credito`
- `transferencia_bancaria`
- `pago_servicio`
- `sipare_imss`
- `comprobante_pago`
- `recibo`
- `desconocido`

## Funcionamiento

El clasificador normaliza mayúsculas y acentos, evalúa señales textuales y aplica reglas con precedencia. Por ejemplo:

- `SIPARE` o la combinación `IMSS + INFONAVIT` → SIPARE/IMSS;
- `RECIBO DE LA TRANSFERENCIA`, `SPEI` o `CUENTA DESTINO` → transferencia bancaria;
- `TU RECIBO DE PAGO` o servicios identificables → pago de servicio;
- `FACTURA/CFDI` más UUID, subtotal o IVA → factura fiscal;
- `NOTA DE CRÉDITO` → nota de crédito.

Cada resultado conserva:

- tipo;
- confianza;
- versión de las reglas;
- señales detectadas;
- reglas que justifican la decisión;
- fecha de clasificación.

Nunca se sobrescriben clasificaciones anteriores. Una reclasificación crea una nueva versión, lo que permite comparar cambios cuando ajustemos reglas.

En la revisión, un capturista puede marcar **Este documento sí genera gasto** cuando la clasificación automática sea incorrecta. El backend registra una nueva versión `factura_fiscal` con clasificador `revision_humana`, el tipo anterior, el operador y la revisión que originó el cambio; después permite publicar el registro en Analytics.

## Primer lote real

Las 25 páginas del lote inicial se clasificaron sin repetir OCR:

| Tipo | Páginas | Confianza promedio |
|---|---:|---:|
| Transferencia bancaria | 21 | 95.7% |
| Pago de servicio | 3 | 96.0% |
| SIPARE / IMSS | 1 | 99.0% |

No hubo documentos `desconocido` en esta primera corrida. Estos porcentajes representan confianza de las reglas, no exactitud validada contra etiquetas humanas. La exactitud se medirá cuando el usuario confirme la clasificación o proporcione un archivo de control.

## Siguiente evolución

La taxonomía se ampliará únicamente cuando los documentos reales lo requieran. Para las pruebas de facturas se medirán por separado:

- clasificación correcta como factura;
- extracción de campos;
- cuadre aritmético;
- necesidad de corrección humana.
