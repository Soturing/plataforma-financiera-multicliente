# Especificación funcional — Demo v0.1

Estado: borrador operativo 0.1  
Fecha: 2026-08-09

## 1. Resultado que debe probarse

Un capturista puede cargar una factura, comparar la evidencia original con los datos propuestos, corregirlos si hace falta y aprobar un registro que aparece en una vista consumible por Excel.

La demo se considera exitosa cuando 10 facturas reales y variadas completan el proceso con trazabilidad y sin editar directamente la base de datos.

## 2. Usuarios iniciales

- **Capturista/revisor:** carga, revisa, corrige, aprueba o rechaza.
- **Administrador del piloto:** mantiene catálogos y consulta métricas.
- **Consumidor financiero:** consulta únicamente información final mediante Excel.

La autenticación y los permisos avanzados quedan fuera de v0.1, pero toda acción humana debe conservar el identificador del actor.

## 3. Flujo principal

1. El usuario carga una imagen o PDF e identifica la sucursal.
2. El sistema crea una factura en estado `recibida` y conserva el archivo.
3. OCR produce texto, JSON y métricas de confianza sin sobrescribir resultados previos.
4. La IA transforma un resultado OCR en una propuesta estructurada y registra modelo y versión de reglas.
5. El motor ejecuta validaciones determinísticas.
6. La factura entra a la bandeja de revisión.
7. La persona compara evidencia, propuesta y alertas.
8. Puede aprobar, corregir y aprobar, o rechazar.
9. La aprobación crea una versión inmutable del registro final.
10. Las vistas de `analytics` exponen únicamente registros finales vigentes.

## 4. Campos mínimos

### Identidad y procedencia

- UUID fiscal
- serie y folio
- sucursal
- archivo original
- canal de ingreso
- fecha y hora de recepción

### Emisor y documento

- proveedor
- RFC del emisor
- fecha de emisión
- moneda
- método de pago
- forma de pago

### Importes

- subtotal
- descuento
- IVA
- otros impuestos
- total

### Clasificación administrativa

- categoría
- subcategoría
- centro de costo
- semana ISO, calculada y no capturada por IA
- observaciones

## 5. Validaciones mínimas

- UUID no duplicado cuando esté disponible.
- RFC con formato plausible.
- Fecha válida y no futura fuera de tolerancia.
- Importes no negativos y total mayor a cero.
- El total es obligatorio y mayor a cero; subtotal, IVA y demás desglose son opcionales.
- El cuadre `subtotal - descuento + iva + otros_impuestos = total` genera una advertencia, no bloquea la aprobación.
- Proveedor, sucursal y categoría pertenecen a catálogos válidos.
- La subcategoría es opcional; cuando se captura, pertenece a la categoría elegida.
- La factura tiene resultado OCR e interpretación antes de aprobarse.

Durante el piloto, todas las facturas requieren revisión humana aunque superen los umbrales de confianza.

## 6. Estados

```text
recibida
ocr_procesando
ocr_completado
ia_procesando
ia_completada
validando
requiere_revision
aprobada
rechazada
error
```

El backend controla las transiciones; un cliente no puede elegir arbitrariamente el siguiente estado.

## 7. Auditoría

- Nunca se sobrescribe un resultado OCR o una interpretación: se crea una nueva versión.
- Cada corrección guarda campo, valor propuesto, valor corregido, persona, fecha y motivo opcional.
- Cada factura final conserva quién aprobó, cuándo y qué interpretación originó el resultado.
- Las reglas y modelos utilizados quedan versionados.

## 8. Fuera de alcance de v0.1

- WhatsApp Business y n8n.
- Aprobación totalmente automática.
- Inventarios y cuentas por pagar.
- Pólizas contables y conciliación bancaria.
- Detección avanzada de cambios de precio.
- Portal para proveedores o gerentes.
- Estado de resultados completo con ventas, nómina y demás fuentes.

## 9. Métricas del piloto

- porcentaje de campos correctos antes de revisión;
- porcentaje de facturas corregidas;
- campos corregidos con mayor frecuencia;
- tiempo medio de revisión;
- errores y duplicados detectados;
- porcentaje de facturas que llegan correctamente a analytics.

## 10. Información de negocio pendiente

- Catálogo real de restaurantes y sucursales.
- Categorías, subcategorías y centros de costo vigentes.
- Campos exactos del Excel actual.
- Reglas proveedor → clasificación.
- Tratamiento esperado de notas de crédito, propinas, IEPS, retenciones y facturas multiconcepto.
- Identidad que se usará para registrar al capturista durante la demo.
