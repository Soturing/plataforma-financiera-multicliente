# Preparación del lote de facturas

Cuando se solicite el lote, cargar aproximadamente 100 documentos reales. No es necesario renombrarlos manualmente.

## Formatos aceptados

- JPG, JPEG, PNG o WEBP para fotografías.
- PDF para facturas digitales o escaneadas.
- Máximo inicial: 15 MB por archivo.

## Variedad deseable

- Los cuatro restaurantes y distintas sucursales.
- Proveedores recurrentes y desconocidos.
- Fotografías claras, inclinadas, oscuras y parcialmente dañadas.
- Facturas digitales y tickets fotografiados.
- IVA, IEPS, retenciones, descuentos y notas de crédito.
- Facturas de una categoría y de múltiples conceptos.
- Al menos algunos duplicados conocidos para medir detección.

## Archivo de control recomendado

Si existe, acompañar el lote con Excel o CSV que contenga el resultado capturado actualmente. Los campos ideales son:

- nombre del archivo;
- sucursal;
- proveedor y RFC;
- UUID;
- fecha;
- subtotal, descuento, IVA, otros impuestos y total;
- categoría y subcategoría;
- observaciones o particularidades.

Este archivo será la verdad de referencia para medir precisión por campo. No se modificará durante la evaluación.

## Privacidad

Las facturas pueden contener información fiscal y comercial sensible. El lote se mantendrá dentro del workspace local durante la etapa de análisis. Antes de enviar documentos a cualquier API externa, se presentará para supervisión la opción de proveedor, los datos enviados, conservación, costo estimado y estrategia de anonimización cuando aplique.
