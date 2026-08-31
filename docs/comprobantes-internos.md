# Comprobantes internos

Este módulo registra gastos reales de proveedores informales o irregulares cuando todavía no existe un CFDI. El documento generado es evidencia de control interno: no se presenta como factura ni cambia automáticamente la deducibilidad fiscal.

## Flujo

```text
Capturista o gerente
        ↓
Captura proveedor, gasto y clasificación
        ↓
¿Pago en efectivo?
  ├─ Sí → exige firma/aceptación del proveedor
  └─ No → firma opcional
        ↓
¿Importe?
  ├─ Hasta $300,000 → una autorización
  └─ Más de $300,000 → no se permite registrar
        ↓
Comprobante aprobado
        ↓
analytics.movimientos_gasto
        ↓
¿Llega CFDI después?
  ├─ No → conserva estado "no deducible"
  └─ Sí → se vincula y el comprobante deja de sumar por separado
```

## Datos y controles

- Folio automático con formato `CI-AÑO-000001`.
- Número documental principal: se captura el número de factura, nota, ticket o recibo; cuando no existe, se genera con la fecha `DDMMYYYY`.
- Búsqueda global por número documental para recuperar tanto archivos cargados como comprobantes internos.
- Catálogo reutilizable de proveedores informales, con teléfono y giro opcionales.
- Evidencia anexa opcional en imagen o PDF.
- Categoría y centro de costo obligatorios; subcategoría opcional.
- Cada gasto pertenece a una sola sucursal; no se permiten pagos cruzados.
- PDF descargable con responsables, autorización y leyenda fiscal.
- Estados auditables: pendiente, aprobado, rechazado y sustituido.

## API principal

- `POST /api/v1/comprobantes-internos`
- `GET /api/v1/comprobantes-internos`
- `POST /api/v1/comprobantes-internos/{id}/aprobar`
- `POST /api/v1/comprobantes-internos/{id}/rechazar`
- `POST /api/v1/comprobantes-internos/{id}/sustituir`
- `GET /api/v1/comprobantes-internos/{id}/pdf`
- `GET /api/v1/comprobantes-internos/{id}/evidencia`
