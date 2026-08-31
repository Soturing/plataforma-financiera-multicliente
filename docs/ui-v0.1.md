# Interfaz mínima — v0.1

## Objetivo

Transformar el trabajo del capturista: dejar de transcribir facturas completas y concentrarse en revisar excepciones, corregir campos y aprobar.

## Vista 1 — Bandeja y carga

La pantalla inicial contiene únicamente:

- métricas de pendientes, errores y casos listos;
- botón para cargar una factura;
- bandeja ordenada primero por errores;
- proveedor, sucursal, resultado de validaciones y total.

La carga incluye datos simulados en una sección secundaria claramente marcada. Esta sección desaparecerá cuando se conecte el OCR real; no condiciona el resto de la interfaz.

## Vista 2 — Revisión

Distribución de escritorio:

```text
┌────────────────────────────┬─────────────────────────┐
│ Documento original         │ Datos interpretados     │
│                            │                         │
│ imagen o PDF               │ alertas                 │
│                            │ campos editables        │
│                            │ validaciones            │
└────────────────────────────┴─────────────────────────┘
│ Rechazar       cambios detectados          Aprobar  │
└──────────────────────────────────────────────────────┘
```

En móvil, el documento aparece antes que los campos y las decisiones permanecen fijas en la parte inferior.

## Reglas de experiencia

- El documento original siempre es la fuente de verdad visible.
- Los campos modificados se resaltan y el botón cambia a `Guardar y aprobar`.
- No existe un botón separado de guardar: la corrección y la decisión forman una sola transacción.
- Rechazar exige un motivo.
- Los errores se muestran antes que mensajes informativos.
- El usuario nunca interactúa con confianza OCR, prompts, modelos ni tablas internas.
- La aprobación con importes descuadrados es bloqueada por el backend, incluso si la UI intenta enviarla.

## Pendiente de validación con el capturista

- Tamaño legible del documento en el equipo que realmente utilizará.
- Orden natural de los campos.
- Si usa teclado, ratón o pantalla táctil.
- Campos que revisa siempre y campos que solo revisa ante una alerta.
- Vocabulario utilizado para rechazo, devolución y factura inválida.
- Necesidad de atajos de teclado para aprobar y pasar a la siguiente factura.
