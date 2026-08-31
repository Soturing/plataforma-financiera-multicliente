# Facturación IA — Demo v0.1

Prototipo auditable de una plataforma financiera multicliente. El repositorio utiliza exclusivamente organizaciones, proveedores e importes sintéticos.

## Objetivo de la demo

Demostrar con fixtures sintéticos el recorrido:

```text
Carga → OCR → interpretación → validación → revisión humana → factura final → analytics → Excel
```

En la primera etapa, OCR e IA pueden simularse. Esto permite validar el modelo de datos y el flujo humano antes de contratar o integrar proveedores externos.

## Estructura

```text
db/
  migrations/       Esquema PostgreSQL versionado
  seeds/            Catálogos y datos de demostración
docs/
  especificacion-funcional.md
  decisiones.md
```

## Arranque local

Requisito: PostgreSQL 15 o posterior. Docker Desktop con Compose es la opción recomendada.

```powershell
Copy-Item .env.example .env
# Edite .env y sustituya CAMBIAR_POR_UN_SECRETO_LOCAL por un secreto aleatorio.
docker compose up -d
docker compose ps
```

Si la instalación local utiliza el ejecutable clásico, sustituir `docker compose` por `docker-compose`.

PostgreSQL quedará disponible en `localhost:5432`. Las migraciones y semillas dentro de `db/` se ejecutan al crear el volumen por primera vez.

### Prueba del pipeline

```powershell
Get-Content -Raw db/tests/001_pipeline_smoke.sql |
  docker-compose exec -T postgres psql -U facturas_app -d facturas_demo
```

La prueba recorre todas las capas, verifica la fila de analytics y ejecuta `ROLLBACK`, por lo que no deja datos ficticios.

## Fronteras del sistema

- OCR conserva evidencia; no determina el asiento final.
- La IA propone datos estructurados; no ejecuta SQL libre.
- Las validaciones matemáticas, fiscales y de duplicidad pertenecen al código y PostgreSQL.
- La persona revisora aprueba, corrige o rechaza.
- Solo los movimientos aprobados —facturas finales o comprobantes internos autorizados— alimentan `analytics.movimientos_gasto`.

## Periodificación de gastos fijos

Al aprobar una factura o generar un comprobante clasificado como `FIJOS`, el capturista puede elegir una aplicación semanal, mensual, bimestral o personalizada. El documento conserva la fecha y el total pagado, mientras el Estado de Resultados distribuye el importe en partes iguales entre las semanas ISO que tengan al menos cuatro días dentro del periodo; cualquier diferencia de centavos se asigna a la última semana.

La periodicidad puede recordarse por proveedor y subcategoría para sugerirla automáticamente en capturas posteriores. Cada gasto pertenece siempre a una sola sucursal.

Las facturas aprobadas pueden editarse desde Analytics o desde el buscador por número. Cada guardado crea una nueva versión, conserva las correcciones en auditoría y reemplaza el movimiento vigente sin duplicarlo. También puede desactivarse su impacto financiero mediante la casilla `Esta factura genera gasto en Analytics`.

## Próximo incremento

Evaluar proveedores de OCR e IA después de validar el flujo con documentos sintéticos.

## Backend FastAPI

Crear el entorno e instalar dependencias:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Iniciar el servidor:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

- API: `http://127.0.0.1:8000`
- Interfaz del capturista: `http://127.0.0.1:8000/`
- Documentación interactiva: `http://127.0.0.1:8000/docs`
- Estado: `http://127.0.0.1:8000/health`

Ejecutar pruebas:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

El flujo integrado probado incluye carga, OCR/IA simulados, bandeja de revisión, aprobación y publicación en `analytics.facturas_consumo`.

Los PDFs multipágina pueden cargarse como lotes. El original se conserva y cada página se registra como una factura independiente vinculada al lote.

La carga masiva separa duplicados exactos por huella SHA-256 y pares XML/PDF por UUID fiscal. La pantalla principal muestra una bandeja independiente para revisarlos y descartarlos manualmente sin afectar el documento original aprobado.

Los PDF digitales se leen primero mediante su capa de texto embebida. PaddleOCR se ejecuta localmente solo como respaldo para imágenes o documentos escaneados. Los PDF multipágina cargados como documentos individuales se conservan completos. Consulta [docs/ocr-local.md](docs/ocr-local.md) para arquitectura, operación y limitaciones.

La clasificación previa a la interpretación está documentada en [docs/clasificacion-documental.md](docs/clasificacion-documental.md).

Consulta [docs/api-v0.1.md](docs/api-v0.1.md) para ver los endpoints y [docs/lote-facturas.md](docs/lote-facturas.md) para preparar lotes de prueba sintéticos.

La política de repositorio prohíbe versionar datos o entregables de clientes. Consulte [docs/seguridad/politica-repositorio.md](docs/seguridad/politica-repositorio.md).

La interfaz y sus decisiones operativas están descritas en [docs/ui-v0.1.md](docs/ui-v0.1.md).

El módulo móvil de gastos sin CFDI, sus niveles de autorización y su sustitución posterior por factura están descritos en [docs/comprobantes-internos.md](docs/comprobantes-internos.md).

## Catálogo y aprendizaje supervisado

La ruta `#/catalogos` permite crear o editar proveedores, registrar alias OCR y mantener su clasificación contable sugerida. Una corrección solo se convierte en memoria cuando el capturista marca explícitamente **Recordar alias** o **Recordar clasificación**; cada aprendizaje queda auditado.

La plantilla se descarga desde la misma pantalla o desde:

```text
http://127.0.0.1:8000/api/v1/proveedores/plantilla
```

El importador acepta XLSX, CSV y TSV, presenta una vista previa y no escribe datos si alguna fila tiene errores. Los documentos de CEDIS pueden entrar como sucursal `POR-ASIGNAR`, pero esa condición bloquea la aprobación hasta que el capturista seleccione una sucursal real.

La bandeja permite seleccionar uno o varios documentos pendientes y eliminarlos después de una confirmación explícita. Los documentos aprobados o publicados en Analytics están protegidos. Los lotes en curso incluyen la acción **Detener**; la cancelación es cooperativa, impide iniciar las páginas restantes y descarta cualquier resultado OCR que termine después de la cancelación. Un lote cancelado puede eliminarse completo y cada documento retirado conserva una entrada de auditoría.

## Estado de Resultados y punto de equilibrio

La ruta `#/finanzas` presenta el Estado de Resultados gerencial por semana ISO y sucursal:

```text
Ventas netas
− Costos variables
= Margen de contribución
− Base semanal de gastos fijos
= Utilidad operativa
```

El punto de equilibrio se calcula como `gastos fijos / margen de contribución porcentual`. Las ventas y bases fijas incluidas inicialmente están identificadas como datos demo; los gastos documentados provienen de facturas y comprobantes aprobados. La tabla `finance.ventas` queda preparada para sustituir la semilla por ventas manuales o una futura integración con WANSOFT.

Debajo del Estado de Resultados se muestra el detalle auditable de los documentos que integran cada sección de gasto. Cada tabla indica proveedor, fecha, monto aplicado, forma de pago, semana, folio y sucursal; su total debe conciliar con el subtotal correspondiente. Cuando un gasto está periodificado, también se distingue la semana original del documento.

El botón **Descargar reporte PDF** genera en el momento un reporte semanal de compras de Restaurante y Barra usando el año, semana y sucursal seleccionados. La plantilla incluye resumen ejecutivo, comparación con la semana anterior y el promedio de cuatro semanas, gráficas, desglose por sucursal, proveedores y detalle documental. La generación es determinista y no consume servicios de IA.

Las únicas categorías superiores activas son `FIJOS` y `VARIABLES`. Las áreas operativas (`BARRA`, `COCINA`, `ADMINISTRACION`, `GENERAL`) se administran como centros de costo desde `#/catalogos`.

El mismo módulo financiero incluye captura diaria editable de ventas por efectivo, dólares y tipo de cambio, Rappi, Uber, Visa y Amex. Crédito, conversión, venta neta y ticket promedio se calculan automáticamente. Un segundo cuadro concilia la venta contra `OTRO`, `APLICACIONES`, `ALIMENTOS` y `BEBIDAS`, además de faltantes, sobrantes y visitas.

También se puede importar una captura PNG, JPG o WEBP del formato semanal actual. El OCR local identifica el año, la semana, los siete días, métodos de pago, desglose comercial y visitas. La extracción se carga como vista previa editable y no modifica la base de datos hasta que el capturista pulsa **Guardar ventas de la semana**. La sucursal se elige antes de analizar la imagen.

En el encabezado de ventas, `PLATAFORMAS` y `RAPPI` se interpretan como nombres equivalentes y ambos se almacenan en el campo Rappi.

El año, la semana y la sucursal seleccionados quedan reflejados en la dirección `#/finanzas?...`, por lo que una recarga de la pantalla conserva el periodo consultado. Las respuestas antiguas de consultas concurrentes se descartan para evitar que la interfaz regrese a otra semana.

La semana ISO 30 de 2026 para `DEMO-A` contiene únicamente datos sintéticos para validar la captura diaria y la conciliación del desglose comercial.

## Reportes financieros

La ruta `#/reportes` está separada del Estado de Resultados y reúne los dos formatos semanales existentes junto con un generador gerencial configurable. El modo mensual utiliza las semanas ISO que tienen al menos cuatro días dentro del mes, agrega las tres sucursales o una unidad seleccionada y compara automáticamente contra el mes anterior.

El modo comparativo permite elegir hasta 16 semanas del mismo año ISO. En ambos casos se puede decidir mediante checklist qué bloques incluir: resumen, comparación mensual, Estado de Resultados, ventas, alimentos, bebidas, nómina, gastos, punto de equilibrio, sucursales, tendencia y principales movimientos. El PDF se genera con los datos vigentes y no modifica ninguna cifra financiera.

## Inferencia de sucursal por consumo

Cuando una factura de CEDIS no incluye correctamente al receptor, el sistema busca productos normalizados en el texto OCR y suma reglas ponderadas por restaurante. Los productos distintivos pesan más que los compartidos; por ejemplo, `TORERITA`, `PULPA NEGRA` y `RIB EYE` son señales fuertes, mientras `SIRLOIN` y `DIEZMILLO` no deciden por sí solos.

Una combinación con confianza alta puede preseleccionar la sucursal únicamente si el documento entró como `POR-ASIGNAR`. La pantalla de revisión siempre muestra productos, puntajes y confianza, y permite corregir la selección. La sugerencia y la sucursal finalmente confirmada quedan registradas en `audit.inferencias_sucursal` para medir precisión y alimentar reglas futuras.

## Hoja de ruta

Los siguientes frentes del producto están registrados —todavía no implementados— en [docs/roadmap-producto.md](docs/roadmap-producto.md): identidad segura y preferentemente sin contraseñas, control de acceso por vigencia del servicio, rediseño de reportes y arquitectura reutilizable para múltiples restaurantes.
