# Categorías de gasto

Definición vigente de D-017. Las categorías son fijas; las subcategorías se editan desde `#/catalogos`.

| Categoría | Clave | Tipo | Entra por | Subcategorías |
|---|---|---|---|---|
| Gastos fijos | `FIJOS` | fijo | Factura, solo proveedores de la lista de fijos | Editables |
| Nómina | `NOMINA` | fijo | Captura manual semanal por sucursal | No aplica |
| Comisiones | `COMISIONES` | variable | Módulo de comisiones (proyección y cierre real) | No aplica |
| Variables operativos | `VARIABLES_OPERATIVOS` | variable | Factura | Sin predefinidas |
| Gastos imprevistos | `IMPREVISTOS` | variable | Factura | Editables |
| Mantenimiento | `MANTENIMIENTO` | variable | Factura | Editables |
| Gasolina | `GASOLINA` | variable | Factura | Editables |
| Gastos Barra | `GASTOS_BARRA` | variable | Factura | Editables (inicial: Bebidas) |
| Gastos Restaurantes | `GASTOS_RESTAURANTE` | variable | Factura | Editables (inicial: Insumos) |

## Reglas

- **Fijos:** un proveedor solo puede clasificarse como fijo si antes se dio de alta en la lista de gastos fijos (`#/catalogos`, tabla `catalog.gastos_fijos`). Al darlo de alta se registran su subcategoría y su periodicidad sugerida; el servidor rechaza facturas, comprobantes y reglas FIJOS de proveedores fuera de la lista o desactivados.
- **Comisiones** (por sucursal / razón social): Visa, Amex, Banco, Apps y Servicios. Cada una tiene un porcentaje ajustable sobre una base (ventas Visa, Amex, Rappi/Uber) o un monto fijo para proyectar. Al cerrar el mes se captura el importe real, que sustituye a la proyección.
- **Nómina:** captura manual por semana y sucursal; mientras no exista, el Estado de Resultados usa la provisión estimada.
- **Estado de Resultados:** ventas − costos variables = margen de contribución − gastos fijos (Fijos + Nómina) = utilidad operativa.
- Una cuenta bancaria compartida por varias sucursales no está contemplada; se desarrollará cuando se pida.
