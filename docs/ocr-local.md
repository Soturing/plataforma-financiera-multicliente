# Lectura híbrida de documentos

## Motor

- PaddleOCR 3.7.0.
- PaddlePaddle 3.3.1 sobre CPU.
- Modelos PP-OCRv6 tiny para texto latino/español, elegidos para mantener tiempos prácticos sobre CPU.
- MKL-DNN desactivado por compatibilidad estable con Windows.

Las facturas no salen del equipo. Para PDF digitales, el backend utiliza primero el texto embebido mediante pypdf. PaddleOCR se inicializa únicamente para imágenes o PDF sin texto suficiente. La primera ejecución de OCR descarga los modelos oficiales en la caché local de PaddleX; las ejecuciones posteriores reutilizan el mismo modelo.

## Flujo

```text
Factura recibida
      ↓
ocr_procesando
      ↓
¿PDF con texto digital suficiente?
      ├── Sí → extracción nativa multipágina
      └── No → render de páginas → PaddleOCR
      ↓
ocr.resultados
      ↓
Reglas determinísticas
      ↓
ai.interpretaciones
      ↓
Validaciones
      ↓
requiere_revision
```

`ai.interpretaciones` conserva por ahora la salida del extractor determinístico. No se afirma que haya intervenido un LLM; `modelo_ia` se registra como `reglas-deterministicas`.

## Extracción inicial

El extractor reconoce por expresiones y etiquetas:

- proveedor propuesto;
- RFC;
- UUID fiscal;
- fecha en formato día/mes/año;
- subtotal;
- descuento;
- IVA;
- otros impuestos;
- total.

Las reglas no inventan valores. Los campos ausentes quedan en `null` y generan validaciones para revisión humana.

## Operación

- Un PDF multipágina cargado como documento individual permanece unido.
- El lote que divide por páginas se usa solo cuando cada página es una factura independiente.
- La lectura pasa por una cola con workers permanentes (ver [cola-ocr.md](cola-ocr.md)): varios lotes y cargas pueden esperar a la vez sin saturar la CPU, y un worker caído no pierde documentos.
- La UI consulta el avance cada tres segundos mientras hay documentos pendientes.
- Las páginas fallidas quedan en `error` y pueden reintentarse.
- El proceso continúa aunque una página individual falle.

## Rendimiento observado

Las mediciones locales deben ejecutarse únicamente con fixtures sintéticos. Los resultados dependen del hardware, la calidad del documento y si se utiliza texto embebido u OCR; por ello no se versionan muestras ni métricas obtenidas de documentos de clientes.
