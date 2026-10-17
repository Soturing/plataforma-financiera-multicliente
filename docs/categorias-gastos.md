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
- **Comisiones** (por sucursal / razón social): Visa, Amex, Banco, Apps (Uber y Rappi) y Servicios. Cada una tiene un porcentaje ajustable sobre una base (ventas Visa, Amex, crédito, Uber, Rappi o ventas netas) o un monto fijo mensual. Se editan en `#/finanzas > Comisiones del mes` (`finance.comision_parametros`).
  - La semana ISO pertenece al mes de su jueves. La proyección semanal es base × porcentaje; el monto fijo mensual se reparte entre las semanas del mes.
  - Al cerrar el mes se captura el importe real por concepto (`finance.comision_cierres`). Ese importe sustituye a la proyección y se reparte en partes iguales entre las semanas del mes, con el residuo de centavos en la última. Borrar el cierre devuelve la proyección.
  - Los porcentajes se editan sobre proyecciones aún no cerradas; un mes con cierre real no cambia al editar porcentajes.
- **Nómina:** captura manual por semana y sucursal; mientras no exista, el Estado de Resultados usa la provisión estimada.
- **Estado de Resultados:** ventas − costos variables = margen de contribución − gastos fijos (Fijos + Nómina) = utilidad operativa.
- Una cuenta bancaria compartida por varias sucursales no está contemplada; se desarrollará cuando se pida.
