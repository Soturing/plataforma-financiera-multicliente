import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = process.argv[2] || "outputs/019fe95f-1206-7081-8e5d-c310152fb7c6";
await fs.mkdir(outputDir, { recursive: true });

const workbook = Workbook.create();
const instructions = workbook.worksheets.add("Instrucciones");
const providers = workbook.worksheets.add("Proveedores");
const branches = workbook.worksheets.add("Sucursales");
const categories = workbook.worksheets.add("Categorias");
const subcategories = workbook.worksheets.add("Subcategorias");
const costCenters = workbook.worksheets.add("Centros_costo");

const darkGreen = "#174C36";
const green = "#2F7D57";
const softGreen = "#EAF4EE";
const gold = "#C8922F";
const softGold = "#FFF4DC";
const ink = "#17231D";
const muted = "#64746B";
const line = "#DCE5DF";
const white = "#FFFFFF";

function styleHeader(sheet, range) {
  sheet.getRange(range).format = {
    fill: darkGreen,
    font: { bold: true, color: white },
    verticalAlignment: "center",
    wrapText: true,
    borders: { bottom: { color: green, style: "thin" } },
    rowHeight: 30,
  };
}

function styleDataArea(sheet, range) {
  sheet.getRange(range).format = {
    font: { color: ink },
    verticalAlignment: "center",
    borders: { bottom: { color: line, style: "hair" } },
  };
}

instructions.showGridLines = false;
instructions.getRange("A1:F1").merge();
instructions.getRange("A1").values = [["Plantilla maestra · Proveedores y sucursales"]];
instructions.getRange("A1:F1").format = {
  fill: darkGreen,
  font: { bold: true, color: white, size: 18 },
  rowHeight: 40,
  verticalAlignment: "center",
};
instructions.getRange("A3:F3").merge();
instructions.getRange("A3").values = [["Objetivo"]];
instructions.getRange("A3:F3").format = { fill: softGreen, font: { bold: true, color: darkGreen }, rowHeight: 25 };
instructions.getRange("A4:F4").merge();
instructions.getRange("A4").values = [["Completar la identidad canónica de cada proveedor, sus alias conocidos y la clasificación contable que la app sugerirá en futuras capturas."]];
instructions.getRange("A4:F4").format = { wrapText: true, rowHeight: 42, font: { color: ink } };
instructions.getRange("A6:C6").values = [["Paso", "Qué hacer", "Validación"]];
styleHeader(instructions, "A6:C6");
instructions.getRange("A7:C10").values = [
  [1, "Llene una fila por proveedor en la hoja Proveedores.", "Razón social y nombre normalizado son obligatorios."],
  [2, "Separe alias con el carácter |.", "Ej.: PROVEEDOR FICTICIO GAMMA | PROVEEDOR C"],
  [3, "Use únicamente claves disponibles en las hojas de catálogos.", "Subcategoría es opcional y debe corresponder a la categoría."],
  [4, "Cargue el archivo en Catálogo y aprendizaje.", "Revise la vista previa antes de confirmar la importación."],
];
styleDataArea(instructions, "A7:C10");
instructions.getRange("A12:F12").merge();
instructions.getRange("A12").values = [["Campos de Proveedores"]];
instructions.getRange("A12:F12").format = { fill: softGold, font: { bold: true, color: "#704205" }, rowHeight: 25 };
instructions.getRange("A13:C13").values = [["Campo", "Requerido", "Descripción"]];
styleHeader(instructions, "A13:C13");
instructions.getRange("A14:C22").values = [
  ["rfc", "No", "RFC del emisor; dejar vacío para proveedor informal."],
  ["razon_social", "Sí", "Razón social o nombre legal exacto."],
  ["nombre_normalizado", "Sí", "Nombre único que verá el capturista y Analytics."],
  ["nombre_comercial", "No", "Nombre de fachada o marca."],
  ["categoria", "No", "FIJOS o VARIABLES."],
  ["subcategoria", "No", "Ej. RENTA, MANTENIMIENTO, INSUMOS o BEBIDAS."],
  ["centro_costo", "No", "COCINA, BARRA, ADMINISTRACION o GENERAL."],
  ["aliases", "No", "Variantes OCR o nombres históricos separados por |."],
  ["activo", "Sí", "SI o NO."],
];
styleDataArea(instructions, "A14:C22");
instructions.getRange("A24:F24").merge();
instructions.getRange("A24").values = [["Importante · no cambie los encabezados de la hoja Proveedores. La app los usa para validar el archivo."]];
instructions.getRange("A24:F24").format = { fill: softGold, font: { bold: true, color: "#704205" }, wrapText: true, rowHeight: 34 };
instructions.getRange("A:C").format.columnWidth = 25;
instructions.getRange("B:B").format.columnWidth = 47;
instructions.getRange("C:C").format.columnWidth = 55;

providers.showGridLines = false;
providers.getRange("A1:I1").values = [[
  "rfc", "razon_social", "nombre_normalizado", "nombre_comercial", "categoria",
  "subcategoria", "centro_costo", "aliases", "activo",
]];
styleHeader(providers, "A1:I1");
providers.getRange("A2:I201").values = Array.from({ length: 200 }, () => Array(9).fill(null));
styleDataArea(providers, "A2:I201");
providers.getRange("E2:E201").dataValidation = { rule: { type: "list", formula1: "Categorias!$A$2:$A$3" } };
providers.getRange("F2:F201").dataValidation = { rule: { type: "list", formula1: "Subcategorias!$B$2:$B$100" } };
providers.getRange("G2:G201").dataValidation = { rule: { type: "list", formula1: "Centros_costo!$A$2:$A$100" } };
providers.getRange("I2:I201").dataValidation = { rule: { type: "list", values: ["SI", "NO"] } };
providers.getRange("A:A").format.columnWidth = 18;
providers.getRange("B:D").format.columnWidth = 30;
providers.getRange("E:G").format.columnWidth = 19;
providers.getRange("H:H").format.columnWidth = 46;
providers.getRange("I:I").format.columnWidth = 10;
providers.freezePanes.freezeRows(1);

branches.showGridLines = false;
branches.getRange("A1:F1").values = [["clave", "razon_social", "rfc", "restaurante", "nombre_sucursal", "aliases"]];
styleHeader(branches, "A1:F1");
branches.getRange("A2:F5").values = [
  ["DEMO-A", "RESTAURANTE DEMO UNO S.A. DE C.V.", "DEM010101AA1", "RESTAURANTE DEMO UNO", "RESTAURANTE DEMO UNO", "DEMO-A | RESTAURANTE DEMO UNO | RESTAURANTE DEMO UNO"],
  [null, null, null, null, null, null],
  [null, null, null, null, null, null],
  [null, null, null, null, null, null],
];
styleDataArea(branches, "A2:F20");
branches.getRange("A:A").format.columnWidth = 16;
branches.getRange("B:B").format.columnWidth = 38;
branches.getRange("C:C").format.columnWidth = 18;
branches.getRange("D:E").format.columnWidth = 23;
branches.getRange("F:F").format.columnWidth = 48;
branches.freezePanes.freezeRows(1);

categories.showGridLines = false;
categories.getRange("A1:B1").values = [["clave", "nombre"]];
styleHeader(categories, "A1:B1");
categories.getRange("A2:B3").values = [["FIJOS", "Fijos"], ["VARIABLES", "Variables"]];
styleDataArea(categories, "A2:B3");
categories.getRange("A:B").format.columnWidth = 24;
categories.freezePanes.freezeRows(1);

subcategories.showGridLines = false;
subcategories.getRange("A1:C1").values = [["categoria", "clave", "nombre"]];
styleHeader(subcategories, "A1:C1");
subcategories.getRange("A2:C12").values = [
  ["FIJOS", "RENTA", "Renta"], ["FIJOS", "NOMINA_FIJA", "Nómina fija"],
  ["FIJOS", "SERVICIOS_FIJOS", "Servicios fijos"], ["FIJOS", "LICENCIAS", "Licencias y suscripciones"],
  ["VARIABLES", "INSUMOS", "Insumos"], ["VARIABLES", "BEBIDAS", "Bebidas"],
  ["VARIABLES", "MANTENIMIENTO", "Mantenimiento"], ["VARIABLES", "COMISIONES", "Comisiones"],
  ["VARIABLES", "SERVICIOS_VARIABLES", "Servicios variables"], ["VARIABLES", "IMPREVISTOS", "Imprevistos"],
  ["VARIABLES", "OTROS_VARIABLES", "Otros variables"],
];
styleDataArea(subcategories, "A2:C12");
subcategories.getRange("A:C").format.columnWidth = 24;
subcategories.freezePanes.freezeRows(1);

costCenters.showGridLines = false;
costCenters.getRange("A1:B1").values = [["clave", "nombre"]];
styleHeader(costCenters, "A1:B1");
costCenters.getRange("A2:B5").values = [["COCINA", "Restaurante / Cocina"], ["BARRA", "Barra"], ["ADMINISTRACION", "Administración"], ["GENERAL", "General"]];
styleDataArea(costCenters, "A2:B5");
costCenters.getRange("A:B").format.columnWidth = 24;
costCenters.freezePanes.freezeRows(1);

const inspection = await workbook.inspect({ kind: "table", sheetId: "Proveedores", range: "A1:I8", include: "values,formulas", maxChars: 4000 });
await fs.writeFile(path.join(outputDir, "plantilla_catalogo_inspeccion.txt"), inspection.ndjson || String(inspection));

for (const sheetName of ["Instrucciones", "Proveedores", "Sucursales", "Categorias", "Subcategorias", "Centros_costo"]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  const safeName = sheetName.toLowerCase().replaceAll("_", "-");
  await fs.writeFile(path.join(outputDir, `preview-${safeName}.png`), new Uint8Array(await preview.arrayBuffer()));
}

const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(path.join(outputDir, "plantilla_catalogo_proveedores.xlsx"));

console.log(path.resolve(outputDir, "plantilla_catalogo_proveedores.xlsx"));
