# Cola de lectura (OCR)

Desde la migración `030_ocr_job_queue.sql`, leer un documento ya no lanza un proceso por archivo. El API **solo encola**; unos **workers permanentes** toman los trabajos de una cola en PostgreSQL. Así el modelo de OCR se carga una vez por worker y no una vez por documento, y una carga de 100 archivos no satura el servidor.

## Cómo funciona

```text
API (carga, lote, "Procesar")           Workers (python -m app.worker_cli)
        │                                        │
        ▼                                        ▼
 core.trabajos_ocr  ──── FOR UPDATE SKIP LOCKED ──► toma 1 trabajo, lo reserva (lease)
   en_cola                                          lee con HybridTextEngine
        ▲                                           guarda resultado + cierra trabajo
        └──── reintento con espera / reserva vencida ◄── error o worker caído
```

- **Un trabajo por factura activa.** Un índice único impide duplicados: pulsar "Procesar" dos veces no lee dos veces.
- **Sin lecturas dobles.** `SKIP LOCKED` garantiza que dos workers nunca tomen el mismo trabajo.
- **Prioridad.** Una factura subida a mano (1) pasa antes que una carga masiva (3), y esta antes que un lote de PDF (5). Dentro de cada nivel, orden de llegada.
- **Reserva (lease) de 120 s, renovada** cada ≤10 s por un hilo mientras se lee. Si el worker muere, la reserva vence y el trabajo vuelve a la cola sin intervención; la factura regresa a `recibida`.
- **Reintentos.** Un fallo transitorio (memoria, base de datos) se reintenta hasta 3 veces con espera de 30 s, 60 s… Un archivo dañado, protegido o inexistente falla de inmediato: reintentar no lo arregla. Agotados los intentos, la factura queda en `error` con `OCR_ERROR`, como antes, y puede reintentarse desde el lote.
- **Resultado atómico.** Guardar el texto leído y cerrar el trabajo ocurren en una sola transacción. Si el worker perdió su reserva, o la factura se canceló o eliminó mientras se leía, el resultado se descarta.
- **Cancelar un lote** saca de la cola sus trabajos pendientes; el que ya se está leyendo se descarta al terminar.

## Operación

| Qué | Cómo |
|---|---|
| Arrancar workers | `python -m app.worker_cli` (supervisor; usa `FACTURAS_OCR_WORKERS`) |
| Otro número de workers | `python -m app.worker_cli --procesos 3` |
| Vaciar la cola y terminar | `python -m app.worker_cli --una-vez` |
| Ver el estado | `GET /api/v1/cola-ocr` y el indicador de la bandeja |
| Registro del autoarranque | `tmp/ocr-worker.log` |

El supervisor mantiene vivos N procesos worker y reinicia al que muera. Solo puede haber un supervisor por base de datos (candado en PostgreSQL), así que lanzar otro termina de inmediato. Los workers corren con prioridad baja para no quitarle CPU a la interfaz.

**Autoarranque.** Con `FACTURAS_OCR_AUTOSTART_WORKERS=true` (valor por defecto, pensado para la demo local) el API lanza el supervisor al encolar o al ver trabajo pendiente sin workers. En producción conviene `false` y ejecutar `python -m app.worker_cli` como servicio (tarea programada de Windows, NSSM o systemd) con reinicio automático.

**Dimensionamiento.** Cada worker carga su modelo (cientos de MB de RAM) y PaddleOCR ya usa varios hilos de CPU, así que más workers no escalan linealmente en una misma máquina. Mida los segundos por documento reales (`segundos_por_documento` en `/api/v1/cola-ocr`) con documentos representativos antes de fijar el número de workers o el hardware.

## Estado de la cola

`GET /api/v1/cola-ocr` devuelve `en_cola`, `reintentando`, `procesando`, `pendientes`, `fallidos_24h`, `completados_1h`, `segundos_por_documento` (mediana de los últimos 30 min), `eta_segundos`, `workers_activos` y la lista de workers. La bandeja lo consulta cada 12 s y cada 3 s mientras hay documentos pendientes, y avisa si no hay ningún lector activo.

## Mantenimiento

Los workers purgan trabajos cerrados con más de 14 días y registros de workers con más de un día de inactividad.
