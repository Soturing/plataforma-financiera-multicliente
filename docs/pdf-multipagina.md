# PDFs multipágina

## Supuesto de v0.1

Cada página corresponde a una factura completa e independiente.

```text
PDF original (50 páginas)
        ↓
Lote de carga
        ↓
50 PDFs de una página
        ↓
50 registros de factura
```

El PDF original no se altera. Cada página conserva:

- identificador del lote;
- número de página original;
- archivo independiente;
- hash SHA-256 propio;
- sucursal y operador del lote.

## Controles

- Solo se aceptan PDFs válidos.
- Se rechazan PDFs sin páginas o protegidos con contraseña.
- El límite inicial es de 200 páginas y 100 MB.
- Si falla la separación o la escritura en base de datos, se eliminan los archivos parciales.
- Las páginas ingresan como `recibida`; OCR e IA las procesarán posteriormente de manera independiente.
- El botón `Procesar` inicia el worker OCR local. Los lotes nuevos lo inician automáticamente.

## Limitación conocida

La versión actual no agrupa automáticamente facturas que ocupen dos o más páginas. Esa capacidad requerirá clasificación de páginas y detección de continuidad documental. Para el piloto debe utilizarse el supuesto de una factura por página.

## Verificación realizada

Se generó un PDF sintético con tres facturas identificables, se dividió y se volvió a renderizar cada salida. Se confirmó que cada archivo contiene exactamente una página y conserva exclusivamente el contenido visual de su página correspondiente.
