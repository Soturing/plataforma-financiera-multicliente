# API — Demo v0.1

La documentación ejecutable completa está disponible en `/docs` cuando el backend está iniciado.

## Flujo principal

### 1. Cargar factura

`POST /api/v1/facturas`

Formulario multipart:

- `archivo`: JPG, PNG, WEBP o PDF; máximo 100 MB.
- `sucursal_clave`: por ahora `DEMO-01`.
- `creada_por`: nombre o identificador del capturista.

El archivo se almacena en `data/uploads` con un nombre interno aleatorio y SHA-256 para futura detección de duplicados.

Un PDF cargado por este endpoint se conserva como un solo documento aunque tenga varias páginas. El procesador intenta primero leer su capa de texto digital y utiliza PaddleOCR únicamente cuando esa capa no contiene texto suficiente.

### 1.1 Carga masiva de documentos

`POST /api/v1/documentos/carga-masiva`

Formulario multipart:

- `archivos`: entre 1 y 100 PDF o imágenes;
- `sucursal_clave`;
- `creada_por`.

Cada archivo se registra como un documento independiente y comienza a procesarse en segundo plano. La respuesta separa documentos creados, duplicados omitidos y errores de formato. Un PDF multipágina permanece unido.

Los archivos idénticos se separan inmediatamente por SHA-256. Cuando XML y PDF representan el mismo CFDI, el UUID fiscal los vincula después de la extracción. Ambos casos aparecen en `GET /api/v1/duplicados` y quedan fuera de la bandeja normal mientras esperan una decisión.

`POST /api/v1/duplicados/descartar` recibe `duplicado_ids` y `descartado_por`. El descarte conserva el documento original, elimina el archivo redundante y deja una marca auditable; nunca elimina automáticamente una factura aprobada.

### 2. Procesar con datos simulados

`POST /api/v1/facturas/{id}/procesar-simulado`

```json
{
  "proveedor": "Proveedor Ficticio Base",
  "fecha_emision": "2026-08-07",
  "subtotal": "10000.00",
  "iva": "1600.00",
  "total": "11600.00",
  "categoria_clave": "RESTAURANTE",
  "subcategoria_clave": null,
  "centro_costo_clave": "COCINA"
}
```

Este endpoint implementa exactamente el contrato que posteriormente utilizarán los adaptadores de OCR e IA reales.

### 3. Consultar bandeja

`GET /api/v1/revision?limit=50&offset=0`

Devuelve únicamente facturas en `requiere_revision`, priorizadas por errores determinísticos.

### 4. Consultar factura

`GET /api/v1/facturas/{id}`

### 5. Aprobar

`POST /api/v1/facturas/{id}/aprobar`

```json
{"revisada_por": "capturista-01", "comentario": null}
```

### 6. Corregir y aprobar

`POST /api/v1/facturas/{id}/corregir`

```json
{
  "revisada_por": "capturista-01",
  "comentario": "IVA corregido contra la imagen",
  "correcciones": [
    {"campo": "iva", "valor": "1600.00", "motivo": "Lectura OCR incorrecta"},
    {"campo": "total", "valor": "11600.00"}
  ]
}
```

Cada campo modificado se registra por separado en `audit.correcciones`.

### 7. Rechazar

`POST /api/v1/facturas/{id}/rechazar`

```json
{
  "revisada_por": "capturista-01",
  "comentario": "La imagen no corresponde a una factura"
}
```

## Reglas vigentes

- No se puede procesar dos veces una factura activa.
- Un archivo con el mismo SHA-256 se rechaza como duplicado.
- Los documentos clasificados como `factura_fiscal` pueden publicarse directamente en `facturas_finales` y Analytics.
- Si la clasificación automática indica que no genera gasto, el capturista puede confirmarlo manualmente con `forzar_como_gasto: true`; la decisión crea una nueva clasificación versionada de revisión humana.
- Complementos de pago, estados de cuenta y datos bancarios permanecen fuera del gasto salvo corrección humana explícita.
- Solo una factura en `requiere_revision` puede decidirse.
- El total es obligatorio; el cuadre del desglose es una advertencia y no bloquea la aprobación.
- Durante v0.1 toda factura termina en revisión humana.

## Analytics demo

`GET /api/v1/analytics/dashboard` entrega dos vistas separadas: `aprobado`, con información contable final, y `preliminar`, que agrega las facturas fiscales aún pendientes para una demostración claramente identificada como no definitiva. Incluye totales, ticket promedio, categorías, proveedores, restaurantes, tendencia diaria y movimientos recientes.

`GET /api/v1/analytics/exportar.csv` descarga exclusivamente las facturas aprobadas en un CSV UTF-8 compatible con Excel. Los resultados OCR y las interpretaciones internas nunca se incluyen en esta exportación.
- Las decisiones son transaccionales: si falla una operación, no deja registros parciales.

## PDF multipágina

### Crear lote

`POST /api/v1/lotes`

Formulario multipart:

- `archivo`: PDF, máximo 100 MB y 200 páginas por defecto;
- `sucursal_clave`;
- `creada_por`.

Este endpoint debe usarse únicamente cuando cada página representa una factura distinta. El sistema conserva el PDF original, genera un PDF de una página por hoja y crea un documento en estado `recibida` para cada una. Para facturas que ocupan varias páginas debe utilizarse `/api/v1/facturas` o `/api/v1/documentos/carga-masiva`.

### Consultar progreso

`GET /api/v1/lotes`

Devuelve totales por estado: recibidas, procesando, en revisión, aprobadas, rechazadas y con error.

### Procesar con OCR local

`POST /api/v1/lotes/{id}/procesar`

Encola las páginas pendientes (`recibida`, `error`) y responde inmediatamente con `encoladas`. Los workers de la cola las leen en orden; pedirlo otra vez no duplica trabajos. Ver [cola-ocr.md](cola-ocr.md).

### Estado de la cola de lectura

`GET /api/v1/cola-ocr`

Devuelve documentos en cola, leyéndose y reintentando, fallidos en 24 h, segundos por documento, tiempo estimado y workers activos.

### Reclasificar desde OCR guardado

`POST /api/v1/lotes/{id}/reclasificar`

Vuelve a ejecutar las reglas documentales sin repetir OCR y crea una nueva versión de clasificación para cada página.
