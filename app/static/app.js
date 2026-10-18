const app = document.querySelector("#app");
const toast = document.querySelector("#toast");
const sidebar = document.querySelector("#sidebar");
const navToggle = document.querySelector("#nav-toggle");
const money = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN" });
let catalogs = null;
let currentCase = null;
let initialValues = {};
let analyticsData = null;
let providerAdminRows = [];
let providerImportFile = null;
let accountingCatalogRows = null;
let fixedExpenseRows = [];
let ownEntityRows = [];
let financeData = null;
let salesBreakdownData = null;
let financeLoadSequence = 0;
let financialReportOptions = null;
const MAX_FINANCIAL_REPORT_WEEKS = 16;
let salesImageFile = null;
let reviewFlowActive = false;
let reviewQueueQuery = "";
let firstReviewId = null;

function operator() {
  // Con sesión, el servidor usa siempre la identidad de la sesión (D-014).
  if (typeof session !== "undefined" && session.autenticado) return session.nombre;
  return document.querySelector("#operator").value.trim() || "capturista-demo";
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const type = response.headers.get("content-type") || "";
  const body = type.includes("json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = body?.detail;
    if (typeof handleAccessError === "function") handleAccessError(response.status, detail);
    const message = detail && typeof detail === "object" ? (detail.mensaje || detail.codigo) : detail;
    throw new Error(message || (typeof body === "string" && body) || "No se pudo completar la operación");
  }
  return body;
}

function notify(message, error = false) {
  toast.textContent = message;
  toast.className = `toast show${error ? " error" : ""}`;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => toast.className = "toast", 3200);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
}

function isPdfFile(file) {
  return file?.type === "application/pdf" || file?.name?.toLowerCase().endsWith(".pdf");
}

async function bootstrap() {
  await loadSession();
  try {
    const health = await api("/health");
    const status = document.querySelector("#system-status");
    status.classList.add("ok");
    status.innerHTML = `<i></i> ${health.status === "ok" ? "Sistema disponible" : "Revisar sistema"}`;
    document.querySelector("#app-version").textContent = health.version ? `Versión ${health.version}` : "";
    if (!session.autenticado || hasModule("CATALOGOS")) catalogs = await api("/api/v1/catalogos");
  } catch (error) {
    document.querySelector("#system-status").innerHTML = "<i></i> Sin conexión";
    notify(error.message, true);
  }
  route();
}

function route() {
  updateNavigation();
  const match = location.hash.match(/^#\/facturas\/([0-9a-f-]+)$/i);
  if (match) renderReview(match[1]);
  else if (location.hash === "#/bandeja") renderDashboard();
  else if (location.hash === "#/archivo") renderArchive();
  else if (location.hash === "#/recibos") renderReceipts();
  else if (location.hash === "#/analytics") renderAnalyticsDashboard();
  else if (location.hash.startsWith("#/reportes")) renderFinancialReports();
  else if (location.hash.startsWith("#/finanzas")) renderFinanceDashboard();
  else if (location.hash === "#/catalogos") renderProviderAdmin();
  else if (location.hash === "#/accesos") renderAccess();
  else renderHome();
}

function currentRoute() {
  if (!location.hash || location.hash === "#/" || location.hash === "#") return ["home", "Inicio"];
  if (location.hash === "#/bandeja") return ["dashboard", "Bandeja de revisión"];
  if (location.hash === "#/archivo") return ["archive", "Archivo documental"];
  if (location.hash === "#/recibos") return ["receipts", "Comprobantes internos"];
  if (location.hash === "#/analytics") return ["analytics", "Análisis de gastos"];
  if (location.hash.startsWith("#/reportes")) return ["reports", "Reportes financieros"];
  if (location.hash.startsWith("#/finanzas")) return ["finance", "Estado de Resultados"];
  if (location.hash === "#/catalogos") return ["catalogs", "Catálogos y reglas"];
  if (location.hash === "#/accesos") return ["access", "Usuarios y accesos"];
  if (location.hash.startsWith("#/facturas/")) return ["dashboard", "Revisión de documento"];
  return ["home", "Inicio"];
}

async function renderHome() {
  app.replaceChildren(document.querySelector("#home-template").content.cloneNode(true));
  document.querySelector("#show-quick-guide").onclick = () => {
    document.querySelector("#guia-rapida").scrollIntoView({behavior: "smooth", block: "start"});
  };
  if (session.autenticado) {
    app.querySelector(".welcome-copy h1 span, h1 span").textContent = session.nombre.split(" ")[0];
    if (!hasModule("DOCUMENTOS")) {
      ["#home-pending", "#home-invoices", "#home-other"].forEach(selector => {
        document.querySelector(selector).textContent = "—";
      });
      return;
    }
  }
  try {
    const summary = await api("/api/v1/revision/resumen");
    document.querySelector("#home-pending").textContent = summary.total ?? 0;
    document.querySelector("#home-invoices").textContent = summary.facturas ?? 0;
    document.querySelector("#home-other").textContent = summary.otros ?? 0;
  } catch (error) {
    ["#home-pending", "#home-invoices", "#home-other"].forEach(selector => {
      document.querySelector(selector).textContent = "—";
    });
  }
}

function closeNavigation() {
  document.body.classList.remove("nav-open");
  navToggle.setAttribute("aria-expanded", "false");
}

function updateNavigation() {
  const [routeName, sectionName] = currentRoute();
  document.querySelector("#current-section").textContent = sectionName;
  document.querySelectorAll(".side-nav a").forEach(link => {
    const active = link.dataset.route === routeName;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  closeNavigation();
}

navToggle.onclick = () => {
  const open = document.body.classList.toggle("nav-open");
  navToggle.setAttribute("aria-expanded", String(open));
};
document.querySelector("#sidebar-scrim").onclick = closeNavigation;
document.querySelector("#sidebar-upload").onclick = () => {
  if (location.hash !== "#/bandeja") {
    location.hash = "#/bandeja";
    setTimeout(() => document.querySelector("#open-upload")?.click(), 150);
  } else document.querySelector("#open-upload")?.click();
};

async function renderFinanceDashboard() {
  financeLoadSequence += 1;
  salesImageFile = null;
  app.replaceChildren(document.querySelector("#finance-template").content.cloneNode(true));
  const now = new Date();
  const hashQuery = location.hash.split("?")[1] || "";
  const savedPeriod = new URLSearchParams(hashQuery);
  document.querySelector("#finance-year").value = savedPeriod.get("anio_iso") || now.getFullYear();
  document.querySelector("#finance-week").value = savedPeriod.get("semana_iso") || isoWeek(now);
  document.querySelector("#finance-branch").innerHTML += (catalogs?.sucursales || [])
    .filter(item => item.clave !== "POR-ASIGNAR")
    .map(item => `<option value="${escapeHtml(item.clave)}">${escapeHtml(item.restaurante)} · ${escapeHtml(item.nombre)}</option>`).join("");
  document.querySelector("#finance-branch").value = savedPeriod.get("sucursal_clave") || "";
  document.querySelector("#finance-apply").onclick = () => loadFinanceStatement(false);
  document.querySelector("#sales-breakdown-form").onsubmit = submitSalesBreakdown;
  const salesImageInput = document.querySelector("#sales-image-file");
  salesImageInput.onchange = () => {
    salesImageFile = salesImageInput.files[0] || null;
    document.querySelector("#sales-image-name").textContent = salesImageFile?.name || "Ninguna imagen seleccionada";
  };
  document.querySelector("#analyze-sales-image").onclick = analyzeSalesImage;
  await loadFinanceStatement(!savedPeriod.has("anio_iso"));
}

const COMMISSION_BASES = {
  visa: "Ventas Visa", amex: "Ventas Amex", credito: "Ventas con crédito (Visa + Amex)",
  uber: "Ventas Uber", rappi: "Ventas Rappi", ventas_netas: "Ventas netas", monto_mensual: "Monto fijo mensual",
};

async function loadCommissionPanel(requestId) {
  const body = document.querySelector("#commission-rows");
  if (!body || !financeData) return;
  const monday = new Date(`${financeData.periodo.fecha_desde}T00:00:00`);
  const thursday = new Date(monday.getTime() + 3 * 86400000);
  const year = thursday.getFullYear();
  const month = thursday.getMonth() + 1;
  const branch = document.querySelector("#finance-branch").value;
  const query = new URLSearchParams({anio: year, mes: month});
  if (branch) query.set("sucursal_clave", branch);
  const [summary, parameters] = await Promise.all([
    api(`/api/v1/finanzas/comisiones/mes?${query}`),
    api(`/api/v1/finanzas/comisiones/parametros${branch ? `?sucursal_clave=${encodeURIComponent(branch)}` : ""}`),
  ]);
  if (requestId !== financeLoadSequence) return;
  document.querySelector("#commission-period-label").textContent =
    `Mes ${String(month).padStart(2, "0")}/${year}: la proyección usa los porcentajes; el importe real sustituye a la proyección.`;
  body.innerHTML = summary.map(row => `
    <tr>
      <td>${escapeHtml(row.sucursal)}</td><td>${escapeHtml(row.concepto_nombre)}</td>
      <td class="numeric">${money.format(row.proyectado)}</td>
      <td class="numeric"><input type="number" step="0.01" min="0" class="inline-input" data-closing-input="${escapeHtml(row.sucursal_clave)}|${row.concepto}" value="${row.real ?? ""}" placeholder="Sin cierre"></td>
      <td class="numeric">${row.diferencia == null ? "—" : money.format(row.diferencia)}</td>
      <td><button class="button ghost small" data-closing-save="${escapeHtml(row.sucursal_clave)}|${row.concepto}">Guardar</button></td>
    </tr>`).join("") || '<tr><td colspan="6"><div class="empty">Configure porcentajes para proyectar comisiones.</div></td></tr>';
  body.querySelectorAll("[data-closing-save]").forEach(button => button.onclick = async () => {
    const [branchKey, concept] = button.dataset.closingSave.split("|");
    const value = body.querySelector(`[data-closing-input="${branchKey}|${concept}"]`).value;
    try {
      await api("/api/v1/finanzas/comisiones/cierre", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          sucursal_clave: branchKey, concepto: concept, anio: year, mes: month,
          importe_real: value === "" ? null : value, actualizado_por: operator(),
        }),
      });
      notify(value === "" ? "Cierre eliminado; vuelve la proyección" : "Cierre real guardado");
      await loadFinanceStatement(false);
    } catch (error) {
      notify(error.message, true);
    }
  });

  const form = document.querySelector("#commission-parameter-form");
  form.elements.base.innerHTML = Object.entries(COMMISSION_BASES).map(([key, label]) => `<option value="${key}">${label}</option>`).join("");
  form.onsubmit = async event => {
    event.preventDefault();
    if (!branch) { notify("Seleccione una sucursal para editar sus porcentajes", true); return; }
    const fixed = form.elements.base.value === "monto_mensual";
    const value = form.elements.valor.value;
    try {
      await api("/api/v1/finanzas/comisiones/parametros", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          sucursal_clave: branch, concepto: form.elements.concepto.value,
          canal: form.elements.canal.value || null, base: form.elements.base.value,
          porcentaje: fixed ? null : String(Number(value) / 100),
          monto_mensual: fixed ? value : null, actualizado_por: operator(),
        }),
      });
      notify("Parámetro de comisión guardado");
      await loadFinanceStatement(false);
    } catch (error) {
      notify(error.message, true);
    }
  };
  const list = document.querySelector("#commission-parameters");
  list.innerHTML = branch ? (parameters.map(item => `
    <div class="mini-catalog-row"><strong>${escapeHtml(COMMISSION_LABELS[item.concepto])}${item.canal ? ` · ${escapeHtml(item.canal)}` : ""}</strong>
      <small>${escapeHtml(COMMISSION_BASES[item.base])} · ${item.base === "monto_mensual" ? money.format(item.monto_mensual) : `${(Number(item.porcentaje) * 100).toFixed(2)}%`}</small>
      <button class="button ghost small" type="button" data-delete-parameter="${item.id}">Quitar</button></div>`).join("")
    || '<div class="empty">Sin porcentajes configurados para esta sucursal.</div>')
    : '<div class="empty">Seleccione una sucursal para ver y editar sus porcentajes.</div>';
  list.querySelectorAll("[data-delete-parameter]").forEach(button => button.onclick = async () => {
    try {
      await api(`/api/v1/finanzas/comisiones/parametros/${button.dataset.deleteParameter}`, {method: "DELETE"});
      notify("Parámetro eliminado");
      await loadFinanceStatement(false);
    } catch (error) {
      notify(error.message, true);
    }
  });
}

async function loadPayrollPanel(requestId) {
  const body = document.querySelector("#payroll-rows");
  if (!body || !financeData) return;
  const {anio_iso: year, semana_iso: week} = financeData.periodo;
  const branch = document.querySelector("#finance-branch").value;
  const query = new URLSearchParams({anio_iso: year, semana_iso: week});
  if (branch) query.set("sucursal_clave", branch);
  const rows = await api(`/api/v1/finanzas/nomina?${query}`);
  if (requestId !== financeLoadSequence) return;
  document.querySelector("#payroll-period-label").textContent = `Semana ISO ${week} de ${year}: importe capturado a mano por sucursal.`;
  body.innerHTML = rows.map(row => `
    <tr>
      <td>${escapeHtml(row.sucursal)}</td>
      <td class="numeric">${row.estimado == null ? "—" : money.format(row.estimado)}</td>
      <td class="numeric"><input type="number" step="0.01" min="0" class="inline-input" data-payroll-input="${escapeHtml(row.sucursal_clave)}" value="${row.capturado ?? ""}" placeholder="Sin captura"></td>
      <td><input type="text" maxlength="300" data-payroll-note="${escapeHtml(row.sucursal_clave)}" value="${escapeHtml(row.nota || "")}" placeholder="Nota opcional"></td>
      <td><button class="button ghost small" data-payroll-save="${escapeHtml(row.sucursal_clave)}">Guardar</button></td>
    </tr>`).join("");
  body.querySelectorAll("[data-payroll-save]").forEach(button => button.onclick = async () => {
    const key = button.dataset.payrollSave;
    const amount = body.querySelector(`[data-payroll-input="${key}"]`).value;
    try {
      await api("/api/v1/finanzas/nomina", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          sucursal_clave: key, anio_iso: year, semana_iso: week,
          monto: amount === "" ? null : amount,
          nota: body.querySelector(`[data-payroll-note="${key}"]`).value || null,
          actualizado_por: operator(),
        }),
      });
      notify(amount === "" ? "Captura eliminada; se usa el estimado" : "Nómina guardada");
      await loadFinanceStatement(false);
    } catch (error) {
      notify(error.message, true);
    }
  });
}

const COMMISSION_LABELS = {
  VISA: "Terminal Visa", AMEX: "Terminal Amex", BANCO: "Banco", APPS: "Apps", SERVICIOS: "Servicios",
};

function downloadWeeklyPurchaseReport() {
  downloadWeeklyReport("/api/v1/finanzas/reporte-compras.pdf");
}

function downloadWeeklyExecutiveReport() {
  downloadWeeklyReport("/api/v1/finanzas/reporte-ejecutivo.pdf");
}

function downloadBlankExecutiveReport() {
  const params = new URLSearchParams();
  const branch = document.querySelector("#finance-branch").value;
  if (branch) params.set("sucursal_clave", branch);
  const link = document.createElement("a");
  link.href = `/api/v1/finanzas/reporte-ejecutivo-vacio.pdf?${params}`;
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function downloadWeeklyReport(endpoint) {
  const params = new URLSearchParams({
    anio_iso: document.querySelector("#finance-year").value,
    semana_iso: document.querySelector("#finance-week").value,
  });
  const branch = document.querySelector("#finance-branch").value;
  if (branch) params.set("sucursal_clave", branch);
  const link = document.createElement("a");
  link.href = `${endpoint}?${params}`;
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function triggerDownload(url) {
  const link = document.createElement("a");
  link.href = url;
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function filenameFromDisposition(disposition, fallback) {
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (encoded) return decodeURIComponent(encoded[1]);
  const plain = disposition.match(/filename="?([^";]+)"?/i);
  return plain?.[1] || fallback;
}

async function downloadPdf(url, fallbackName) {
  const response = await fetch(url);
  const type = response.headers.get("content-type") || "";
  if (!response.ok) {
    const body = type.includes("json") ? await response.json() : await response.text();
    throw new Error(body.detail || body || "No fue posible generar el PDF");
  }
  if (!type.includes("application/pdf")) {
    throw new Error("El servidor no devolvió un archivo PDF válido");
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filenameFromDisposition(response.headers.get("content-disposition") || "", fallbackName);
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

async function renderFinancialReports() {
  app.replaceChildren(document.querySelector("#financial-reports-template").content.cloneNode(true));
  try {
    financialReportOptions = await api("/api/v1/reportes-financieros/opciones");
    const defaults = financialReportOptions.predeterminado;
    document.querySelector("#report-calendar-year").value = defaults.anio;
    document.querySelector("#report-month").value = defaults.mes;
    document.querySelector("#legacy-report-year").value = defaults.anio_iso;
    document.querySelector("#legacy-report-week").value = defaults.semana_iso;
    const branchOptions = financialReportOptions.sucursales.map(item =>
      `<option value="${escapeHtml(item.clave)}">${escapeHtml(item.restaurante)} · ${escapeHtml(item.nombre)}</option>`
    ).join("");
    document.querySelector("#report-branch").innerHTML += branchOptions;
    document.querySelector("#legacy-report-branch").innerHTML += branchOptions;
    renderFinancialReportSections();
    renderFinancialReportWeeks();
    updateFinancialReportMode();

    document.querySelector("#report-period-mode").onchange = () => {
      updateFinancialReportMode();
      loadFinancialReportPreview();
    };
    document.querySelector("#report-calendar-year").onchange = () => {
      renderFinancialReportWeeks();
      loadFinancialReportPreview();
    };
    document.querySelector("#report-month").onchange = loadFinancialReportPreview;
    document.querySelector("#report-branch").onchange = loadFinancialReportPreview;
    document.querySelector("#report-preview-button").onclick = loadFinancialReportPreview;
    document.querySelector("#report-download-button").onclick = downloadConfigurableFinancialReport;
    document.querySelector("#report-select-available").onclick = () => {
      const inputs = [...document.querySelectorAll("#report-weeks input")];
      inputs.forEach((input, index) => input.checked = index >= inputs.length - MAX_FINANCIAL_REPORT_WEEKS);
      if (inputs.length > MAX_FINANCIAL_REPORT_WEEKS) {
        notify(`Se eligieron las ${MAX_FINANCIAL_REPORT_WEEKS} semanas disponibles más recientes`);
      }
      loadFinancialReportPreview();
    };
    document.querySelector("#report-select-all").onclick = () =>
      document.querySelectorAll("#report-sections input").forEach(input => input.checked = true);
    document.querySelector("#report-clear-sections").onclick = () =>
      document.querySelectorAll("#report-sections input").forEach(input => input.checked = false);
    document.querySelector("#legacy-financial-report").onclick = () => downloadLegacyFinancialReport("/api/v1/finanzas/reporte-ejecutivo.pdf");
    document.querySelector("#legacy-purchase-report").onclick = () => downloadLegacyFinancialReport("/api/v1/finanzas/reporte-compras.pdf");
    document.querySelector("#legacy-blank-report").onclick = downloadLegacyBlankReport;
    await loadFinancialReportPreview();
  } catch (error) {
    notify(error.message, true);
    document.querySelector("#report-preview").innerHTML = `<div class="report-preview-empty"><strong>No se pudo preparar el generador</strong><span>${escapeHtml(error.message)}</span></div>`;
  }
}

function renderFinancialReportSections() {
  document.querySelector("#report-sections").innerHTML = financialReportOptions.secciones.map(item => `
    <label class="report-section-option">
      <input type="checkbox" value="${escapeHtml(item.clave)}" ${item.predeterminada ? "checked" : ""}>
      <span><strong>${escapeHtml(item.nombre)}</strong><small>${escapeHtml(item.descripcion)}</small></span>
    </label>
  `).join("");
}

function renderFinancialReportWeeks() {
  const year = Number(document.querySelector("#report-calendar-year").value);
  const available = financialReportOptions.periodos
    .filter(item => Number(item.anio_iso) === year)
    .sort((a, b) => Number(a.semana_iso) - Number(b.semana_iso));
  const firstSelected = Math.max(available.length - 2, 0);
  document.querySelector("#report-weeks").innerHTML = available.length
    ? available.map((item, index) => `<label><input type="checkbox" value="${item.semana_iso}" ${index >= firstSelected ? "checked" : ""}><span>S${String(item.semana_iso).padStart(2, "0")}</span></label>`).join("")
    : '<div class="empty">No hay semanas con información para este año.</div>';
}

function updateFinancialReportMode() {
  const custom = document.querySelector("#report-period-mode").value === "semanas";
  document.querySelector("#report-month-label").classList.toggle("hidden", custom);
  document.querySelector("#report-week-selector").classList.toggle("hidden", !custom);
  document.querySelector("#report-calendar-year-label").firstChild.textContent = custom ? "Año ISO" : "Año";
}

function financialReportParams(includeSections = false) {
  const mode = document.querySelector("#report-period-mode").value;
  const params = new URLSearchParams({
    modo: mode,
    anio: document.querySelector("#report-calendar-year").value,
  });
  if (mode === "mensual") {
    params.set("mes", document.querySelector("#report-month").value);
  } else {
    const weeks = [...document.querySelectorAll("#report-weeks input:checked")].map(input => input.value);
    if (!weeks.length) throw new Error("Selecciona al menos una semana para el reporte");
    if (weeks.length > MAX_FINANCIAL_REPORT_WEEKS) {
      throw new Error(`Selecciona como máximo ${MAX_FINANCIAL_REPORT_WEEKS} semanas para el reporte`);
    }
    params.set("semanas", weeks.join(","));
  }
  const branch = document.querySelector("#report-branch").value;
  if (branch) params.set("sucursal_clave", branch);
  if (includeSections) {
    const sections = [...document.querySelectorAll("#report-sections input:checked")].map(input => input.value);
    if (!sections.length) throw new Error("Selecciona al menos un bloque para el PDF");
    params.set("secciones", sections.join(","));
  }
  return params;
}

async function loadFinancialReportPreview() {
  const preview = document.querySelector("#report-preview");
  const button = document.querySelector("#report-preview-button");
  if (!preview || !button) return;
  button.disabled = true;
  preview.classList.add("loading");
  try {
    const data = await api(`/api/v1/reportes-financieros/resumen?${financialReportParams()}`);
    renderFinancialReportPreview(data);
  } catch (error) {
    preview.innerHTML = `<div class="report-preview-empty"><strong>No fue posible calcular el periodo</strong><span>${escapeHtml(error.message)}</span></div>`;
    notify(error.message, true);
  } finally {
    button.disabled = false;
    preview.classList.remove("loading");
  }
}

function reportVariation(current, previous) {
  if (!Number(previous)) return "Sin base";
  const change = (Number(current) - Number(previous)) / Math.abs(Number(previous));
  return `${change >= 0 ? "+" : ""}${(change * 100).toFixed(1)}%`;
}

function renderFinancialReportPreview(data) {
  const totals = data.actual.totales;
  const indicators = data.actual.indicadores;
  const previous = data.comparacion?.datos?.totales;
  const comparisonReady = Boolean(previous && data.actual.cobertura.completa && data.comparacion.datos.cobertura.completa);
  const coverage = data.actual.cobertura;
  const weeks = data.periodo.semanas.map(item => `S${String(item.semana_iso).padStart(2, "0")}`).join(" · ");
  document.querySelector("#report-preview").innerHTML = `
    <div class="report-preview-header"><span>VISTA PREVIA</span><strong>${escapeHtml(data.titulo)}</strong><small>${escapeHtml(weeks)}</small></div>
    ${coverage.completa ? "" : `<div class="report-coverage-warning"><strong>Corte parcial</strong><span>Faltan ventas en ${coverage.semanas_sin_ventas.map(week => `S${String(week).padStart(2, "0")}`).join(" y ")}. El PDF se marcará como preliminar.</span></div>`}
    <div class="report-preview-metrics">
      <div><span>Ventas</span><strong>${money.format(totals.ventas)}</strong>${comparisonReady ? `<small>${reportVariation(totals.ventas, previous.ventas)} vs. ${escapeHtml(data.comparacion.etiqueta)}</small>` : ""}</div>
      <div><span>Utilidad operativa</span><strong class="${Number(totals.utilidad_operativa) < 0 ? "negative-text" : "positive-text"}">${money.format(totals.utilidad_operativa)}</strong>${comparisonReady ? `<small>${reportVariation(totals.utilidad_operativa, previous.utilidad_operativa)} vs. periodo anterior</small>` : ""}</div>
      <div><span>Margen operativo</span><strong>${percent(indicators.margen_operativo)}</strong><small>Nómina ${percent(indicators.nomina_pct)}</small></div>
      <div><span>Punto de equilibrio</span><strong>${indicators.punto_equilibrio == null ? "No calculable" : money.format(indicators.punto_equilibrio)}</strong><small>Seguridad ${percent(indicators.margen_seguridad_pct)}</small></div>
    </div>
    <div class="report-preview-summary">
      <div><span>Alimentos</span><strong>${money.format(totals.compras_alimentos)}</strong><small>${percent(indicators.compras_alimentos_pct)} de su venta</small></div>
      <div><span>Bebidas</span><strong>${money.format(totals.compras_bebidas)}</strong><small>${percent(indicators.compras_bebidas_pct)} de su venta</small></div>
      <div><span>Nómina</span><strong>${money.format(totals.nomina)}</strong><small>${data.actual.semanas.length} semanas</small></div>
    </div>`;
}

async function downloadConfigurableFinancialReport() {
  const button = document.querySelector("#report-download-button");
  const label = button.textContent;
  try {
    button.disabled = true;
    button.textContent = "Generando PDF…";
    await downloadPdf(
      `/api/v1/reportes-financieros/reporte.pdf?${financialReportParams(true)}`,
      "reporte-financiero.pdf",
    );
    notify("Reporte PDF descargado");
  } catch (error) {
    notify(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

function downloadLegacyFinancialReport(endpoint) {
  const params = new URLSearchParams({
    anio_iso: document.querySelector("#legacy-report-year").value,
    semana_iso: document.querySelector("#legacy-report-week").value,
  });
  const branch = document.querySelector("#legacy-report-branch").value;
  if (branch) params.set("sucursal_clave", branch);
  triggerDownload(`${endpoint}?${params}`);
}

function downloadLegacyBlankReport() {
  const params = new URLSearchParams();
  const branch = document.querySelector("#legacy-report-branch").value;
  if (branch) params.set("sucursal_clave", branch);
  triggerDownload(`/api/v1/finanzas/reporte-ejecutivo-vacio.pdf?${params}`);
}

function isoWeek(date) {
  const target = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const day = target.getUTCDay() || 7;
  target.setUTCDate(target.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(target.getUTCFullYear(), 0, 1));
  return Math.ceil((((target - yearStart) / 86400000) + 1) / 7);
}

async function loadFinanceStatement(useLatest = false) {
  const requestId = ++financeLoadSequence;
  const year = document.querySelector("#finance-year");
  const week = document.querySelector("#finance-week");
  const branch = document.querySelector("#finance-branch").value;
  const query = new URLSearchParams();
  if (!useLatest) {
    query.set("anio_iso", year.value);
    query.set("semana_iso", week.value);
  }
  if (branch) query.set("sucursal_clave", branch);
  try {
    const loadedFinance = await api(`/api/v1/finanzas/estado-resultados?${query}`);
    if (requestId !== financeLoadSequence) return;
    financeData = loadedFinance;
    year.value = loadedFinance.periodo.anio_iso;
    week.value = loadedFinance.periodo.semana_iso;
    renderFinanceStatement(loadedFinance);
    await loadSalesBreakdown(requestId);
    if (requestId !== financeLoadSequence) return;
    await loadCommissionPanel(requestId);
    if (requestId !== financeLoadSequence) return;
    await loadPayrollPanel(requestId);
    if (requestId !== financeLoadSequence) return;
    const persisted = new URLSearchParams({
      anio_iso: String(loadedFinance.periodo.anio_iso),
      semana_iso: String(loadedFinance.periodo.semana_iso),
    });
    if (document.querySelector("#finance-branch").value) {
      persisted.set("sucursal_clave", document.querySelector("#finance-branch").value);
    }
    history.replaceState(null, "", `#/finanzas?${persisted}`);
  } catch (error) {
    notify(error.message, true);
  }
}

async function analyzeSalesImage() {
  const branch = document.querySelector("#finance-branch").value;
  if (!branch) {
    notify("Seleccione la sucursal a la que pertenecen las ventas", true);
    return;
  }
  if (!salesImageFile) {
    notify("Seleccione el XLSX o una imagen del formato semanal", true);
    return;
  }
  const button = document.querySelector("#analyze-sales-image");
  button.disabled = true;
  button.textContent = "Leyendo archivo…";
  try {
    const form = new FormData();
    form.set("archivo", salesImageFile);
    form.set("sucursal_clave", branch);
    form.set("anio_iso", document.querySelector("#finance-year").value);
    form.set("semana_iso", document.querySelector("#finance-week").value);
    const preview = await api("/api/v1/finanzas/ventas-desglose/archivo", {method: "POST", body: form});
    salesBreakdownData = preview;
    document.querySelector("#finance-year").value = preview.periodo.anio_iso;
    document.querySelector("#finance-week").value = preview.periodo.semana_iso;
    renderSalesBreakdown();
    renderWeeklyExpenses();
    const ocr = preview.ocr;
    const result = document.querySelector("#sales-ocr-result");
    result.classList.remove("hidden");
    const sourceLabel = ocr.origen === "xlsx" ? "Lectura estructurada del XLSX" : `${Math.round(Number(ocr.confianza || 0) * 100)}% confianza OCR`;
    result.innerHTML = `<div><strong>Vista previa · ${sourceLabel}</strong><span>Venta neta ${money.format(ocr.conciliacion.venta_neta)} · desglose ${money.format(ocr.conciliacion.total_desglose)}</span></div>${ocr.advertencias.length ? `<ul>${ocr.advertencias.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : '<span class="positive-text">El archivo concilia. Revise las filas y pulse Guardar ventas de la semana.</span>'}`;
    result.scrollIntoView({behavior: "smooth", block: "start"});
    notify("Archivo leído; revise la vista previa antes de guardar");
  } catch (error) {
    notify(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Leer archivo";
  }
}

function percent(value) {
  return value == null ? "—" : `${(Number(value) * 100).toFixed(1)}%`;
}

function amountPercent(value, base) {
  return Number(base || 0) > 0 ? percent(Number(value || 0) / Number(base)) : "—";
}

function renderFinanceStatement(data) {
  const summary = data.resumen;
  document.querySelector("#finance-sales").textContent = money.format(summary.ventas || 0);
  document.querySelector("#finance-variable").textContent = money.format(summary.costos_variables || 0);
  document.querySelector("#finance-fixed").textContent = money.format(summary.gastos_fijos || 0);
  const profit = document.querySelector("#finance-profit");
  profit.textContent = money.format(summary.utilidad_operativa || 0);
  profit.closest("article").classList.toggle("negative", Number(summary.utilidad_operativa) < 0);
  document.querySelector("#finance-period-label").textContent = `Semana ${data.periodo.semana_iso} · ${formatDate(data.periodo.fecha_desde)} al ${formatDate(data.periodo.fecha_hasta)}`;

  const income = data.desglose_ingresos;
  const expenses = data.desglose_gastos;
  const restaurantIndicators = data.indicadores_restaurante || {};
  const foodSales = Number(restaurantIndicators.ventas_alimentos || 0);
  const beverageSales = Number(restaurantIndicators.ventas_bebidas || 0);
  const foodAndBeverageSales = foodSales + beverageSales;
  const incomeTotal = Number(income.total || 0);
  const statementRows = [
    ["INGRESOS EFECTIVO", income.efectivo, "income", amountPercent(income.efectivo, incomeTotal), "Total ingresos"],
    ["INGRESOS USD", income.usd, "income", amountPercent(income.usd, incomeTotal), "Total ingresos"],
    ["INGRESOS RAPPI Y UBER", income.rappi_uber, "income", amountPercent(income.rappi_uber, incomeTotal), "Total ingresos"],
    ["INGRESOS TARJETA DE CRÉDITO", income.tarjeta_credito, "income", amountPercent(income.tarjeta_credito, incomeTotal), "Total ingresos"],
    ["TOTAL INGRESOS", income.total, "subtotal", amountPercent(income.total, incomeTotal), "Total ingresos"],
    ["GASTOS FIJOS", expenses.fijos, "expense", amountPercent(expenses.fijos, foodAndBeverageSales), "Venta alimentos + bebidas"],
    ["GASTOS NÓMINA", expenses.nomina, "expense", amountPercent(expenses.nomina, foodAndBeverageSales), "Venta alimentos + bebidas"],
    ["GASTOS BAR", expenses.bar, "expense", amountPercent(expenses.bar, beverageSales), "Venta de bebidas"],
    ["GASTOS RESTAURANTE", expenses.restaurante, "expense", amountPercent(expenses.restaurante, foodSales), "Venta de alimentos"],
    ["GASTOS MANTENIMIENTO", expenses.mantenimiento, "expense", amountPercent(expenses.mantenimiento, foodAndBeverageSales), "Venta alimentos + bebidas"],
    ["GASTOS COMISIONES", expenses.comisiones, "expense", amountPercent(expenses.comisiones, foodAndBeverageSales), "Venta alimentos + bebidas"],
    ["GASTOS VARIABLES OPERATIVOS", expenses.variables, "expense", amountPercent(expenses.variables, foodAndBeverageSales), "Venta alimentos + bebidas"],
    ["GASTOS GASOLINA", expenses.gasolina, "expense", amountPercent(expenses.gasolina, foodAndBeverageSales), "Venta alimentos + bebidas"],
    ["GASTOS IMPREVISTOS", expenses.imprevistos, "expense", amountPercent(expenses.imprevistos, foodAndBeverageSales), "Venta alimentos + bebidas"],
    ["TOTAL GASTOS", expenses.total, "subtotal expense-total", amountPercent(expenses.total, foodAndBeverageSales), "Venta alimentos + bebidas"],
    [Number(summary.utilidad_operativa) >= 0 ? "GANANCIA" : "PÉRDIDA", summary.utilidad_operativa, Number(summary.utilidad_operativa) >= 0 ? "total" : "total negative-total", amountPercent(summary.utilidad_operativa, incomeTotal), "Total ingresos"],
  ];
  document.querySelector("#income-statement").innerHTML = statementRows.map(([label, value, kind, rate, basis], index) => `
    ${index === 5 ? '<div class="statement-spacer"></div>' : ""}<div class="statement-row ${kind}"><span>${escapeHtml(label)}</span><small class="statement-rate" title="Base: ${escapeHtml(basis)}">${escapeHtml(rate)}</small><strong>${money.format(value || 0)}</strong></div>
  `).join("") + `<div class="statement-basis-note"><strong>Bases de porcentaje</strong><span>Bar sobre venta de bebidas · Restaurante sobre venta de alimentos · Los demás gastos y Total gastos sobre venta de alimentos + bebidas (${money.format(foodAndBeverageSales)}).</span></div>`;
  renderFinanceExpenseDetail(data);

  const breakEven = summary.punto_equilibrio;
  const progress = breakEven && Number(breakEven) > 0 ? Math.min(140, Number(summary.ventas) / Number(breakEven) * 100) : 0;
  const stateLabel = {
    sobre_equilibrio: "Sobre el punto de equilibrio",
    bajo_equilibrio: "Debajo del punto de equilibrio",
    no_calculable: "Margen de contribución no positivo",
    sin_ventas: "Sin ventas registradas",
  }[summary.estado_equilibrio];
  document.querySelector("#break-even-content").innerHTML = `
    <div class="break-even-hero ${summary.estado_equilibrio}"><small>Venta mínima semanal</small><strong>${breakEven == null ? "No calculable" : money.format(breakEven)}</strong><span>${escapeHtml(stateLabel)}</span></div>
    <div class="break-even-track"><i style="width:${Math.min(progress, 100)}%"></i><b style="left:${Math.min(100, breakEven ? 100 : 0)}%"></b></div>
    <div class="break-even-labels"><span>Ventas: ${money.format(summary.ventas || 0)}</span><span>Equilibrio: ${breakEven == null ? "—" : money.format(breakEven)}</span></div>
    <dl class="break-even-details"><div><dt>Base fija semanal</dt><dd>${money.format(summary.base_fija_equilibrio || 0)}</dd></div><div><dt>Margen de contribución</dt><dd>${percent(summary.margen_contribucion_pct)}</dd></div><div><dt>Margen de seguridad</dt><dd>${summary.margen_seguridad == null ? "—" : money.format(summary.margen_seguridad)}</dd></div></dl>`;

  document.querySelector("#finance-branch-rows").innerHTML = data.sucursales.length ? data.sucursales.map(item => `
    <tr><td><strong>${escapeHtml(item.restaurante)}</strong><small>${escapeHtml(item.sucursal)}</small></td><td class="numeric">${money.format(item.ventas)}</td><td class="numeric">${money.format(item.costos_variables)}</td><td class="numeric">${money.format(item.gastos_fijos)}</td><td class="numeric ${Number(item.utilidad_operativa) < 0 ? "negative-text" : "positive-text"}">${money.format(item.utilidad_operativa)}</td><td><span class="badge ${item.estado_equilibrio === "sobre_equilibrio" ? "success" : "warning"}">${item.punto_equilibrio == null ? "No calculable" : money.format(item.punto_equilibrio)}</span></td></tr>
  `).join("") : `<tr><td colspan="6" class="empty">No hay movimientos para este periodo.</td></tr>`;

  const maxSales = Math.max(...data.tendencia.map(item => Number(item.ventas)), 1);
  document.querySelector("#finance-trend").innerHTML = data.tendencia.map(item => {
    const salesWidth = Number(item.ventas) / maxSales * 100;
    const profitWidth = Math.max(0, Number(item.utilidad_operativa)) / maxSales * 100;
    return `<div class="finance-trend-row"><strong>S${item.semana_iso}</strong><div><span class="sales-bar" style="width:${salesWidth}%"></span><span class="profit-bar" style="width:${profitWidth}%"></span></div><small>${money.format(item.ventas)} · utilidad ${money.format(item.utilidad_operativa)}</small></div>`;
  }).join("") || `<div class="empty">Sin historial disponible.</div>`;
}

function renderFinanceExpenseDetail(data) {
  const container = document.querySelector("#finance-expense-detail");
  const groups = data.detalle_gastos || {};
  const totals = data.desglose_gastos || {};
  const labels = {
    fijos: "Gastos fijos",
    nomina: "Nómina",
    bar: "Barra",
    restaurante: "Restaurante",
    mantenimiento: "Mantenimiento",
    comisiones: "Comisiones",
    variables: "Variables operativos",
    gasolina: "Gasolina",
    imprevistos: "Imprevistos",
  };
  const order = ["fijos", "nomina", "comisiones", "bar", "restaurante", "mantenimiento", "variables", "gasolina", "imprevistos"];
  const sections = order.filter(key => (groups[key] || []).length || Number(totals[key] || 0));
  if (!sections.length) {
    container.innerHTML = '<div class="empty">No hay gastos aplicados en este periodo.</div>';
    return;
  }
  container.innerHTML = sections.map(key => {
    const rows = groups[key] || [];
    const calculated = rows.reduce((sum, row) => sum + Number(row.monto_aplicado || 0), 0);
    const expected = Number(totals[key] || 0);
    const difference = expected - calculated;
    return `<details class="expense-section">
      <summary><span>${escapeHtml(labels[key] || key)}</span><small>${rows.length} movimiento${rows.length === 1 ? "" : "s"}</small><strong>${money.format(expected)}</strong></summary>
      ${Math.abs(difference) > .01 ? `<div class="expense-reconciliation warning-text">El detalle documental suma ${money.format(calculated)}; existe un ajuste o base configurada de ${money.format(difference)}.</div>` : ""}
      <div class="expense-table-wrap"><table class="expense-detail-table">
        <thead><tr><th>Proveedor</th><th>Fecha</th><th class="numeric">Monto aplicado</th><th>Pago</th><th>Semana</th><th>No. factura</th><th>Sucursal</th></tr></thead>
        <tbody>${rows.map(row => `<tr>
          <td><strong>${escapeHtml(row.proveedor || "Sin proveedor")}</strong>${row.periodificado ? `<small>Documento: ${money.format(row.total_documento || 0)}</small>` : ""}</td>
          <td>${formatDate(row.fecha)}</td>
          <td class="numeric"><strong>${money.format(row.monto_aplicado || 0)}</strong></td>
          <td>${escapeHtml(row.pago || "No especificado")}</td>
          <td>S${row.semana_aplicacion}${row.semana_documento !== row.semana_aplicacion ? `<small>Documento S${row.semana_documento}</small>` : ""}</td>
          <td>${row.tipo_documento === "comprobante_interno" ? escapeHtml(row.folio || "—") : `<a href="#/facturas/${row.documento_origen_id}">${escapeHtml(row.folio || "Abrir")}</a>`}</td>
          <td>${escapeHtml(row.sucursal || row.sucursal_clave || "—")}</td>
        </tr>`).join("") || '<tr><td colspan="7" class="empty">Sin documentos individuales.</td></tr>'}</tbody>
        <tfoot><tr><th colspan="2">Total de la sección</th><th class="numeric">${money.format(calculated)}</th><th colspan="4"></th></tr></tfoot>
      </table></div>
    </details>`;
  }).join("");
}

async function loadSalesBreakdown(requestId = financeLoadSequence) {
  const year = document.querySelector("#finance-year").value;
  const week = document.querySelector("#finance-week").value;
  const branch = document.querySelector("#finance-branch").value;
  const query = new URLSearchParams({anio_iso: year, semana_iso: week});
  if (branch) query.set("sucursal_clave", branch);
  try {
    const loaded = await api(`/api/v1/finanzas/ventas-desglose?${query}`);
    if (requestId !== financeLoadSequence) return;
    salesBreakdownData = loaded;
    renderSalesBreakdown();
  } catch (error) {
    notify(error.message, true);
  }
}

function inputValue(value) {
  return Number(value || 0) === 0 ? "" : Number(value).toFixed(2).replace(/\.00$/, "");
}

function renderWeeklyExpenses() {
  const panel = document.querySelector("#weekly-expenses-preview");
  if (!panel) return;
  const expenses = salesBreakdownData?.gastos || [];
  panel.classList.toggle("hidden", !expenses.length);
  if (!expenses.length) return;
  document.querySelector("#weekly-expenses-rows").innerHTML = expenses.map((item, index) => `
    <tr>
      <td><input type="checkbox" data-weekly-expense="${index}" ${item.incluir !== false ? "checked" : ""}></td>
      <td><span class="badge ${item.area === "barra" ? "warning" : "success"}">${item.area === "barra" ? "Barra" : "Restaurante"}</span></td>
      <td><strong>${escapeHtml(item.proveedor)}</strong></td>
      <td>${formatDate(item.fecha)}</td>
      <td>${escapeHtml(item.descripcion)}</td>
      <td>${escapeHtml(item.pago || "efectivo")}</td>
      <td>${escapeHtml(item.numero_factura || "—")}</td>
      <td class="numeric"><strong>${money.format(item.monto || 0)}</strong></td>
    </tr>`).join("");
  const updateTotal = () => {
    document.querySelectorAll("[data-weekly-expense]").forEach(input => {
      expenses[Number(input.dataset.weeklyExpense)].incluir = input.checked;
    });
    const selected = expenses.filter(item => item.incluir !== false);
    const total = selected.reduce((sum, item) => sum + Number(item.monto || 0), 0);
    document.querySelector("#weekly-expenses-total").textContent = `${selected.length} gastos · ${money.format(total)}`;
  };
  document.querySelectorAll("[data-weekly-expense]").forEach(input => input.onchange = updateTotal);
  updateTotal();
}

function salesInput(index, field, value, disabled, extra = "") {
  return `<input type="number" min="0" step="0.01" data-sales-row="${index}" data-sales-field="${field}" value="${inputValue(value)}" ${disabled ? "disabled" : ""} ${extra}>`;
}

function calculateSalesRow(row) {
  row.conversion_usd = Number(row.dolares || 0) * Number(row.tipo_cambio || 0);
  row.credito = Number(row.visa || 0) + Number(row.amex || 0);
  row.total_calculado = Number(row.efectivo || 0) + row.conversion_usd + Number(row.rappi || 0) + Number(row.uber || 0) + row.credito;
  if (!row.total_capturado_manual) row.monto_neto = row.total_calculado;
  row.total_mix = Number(row.venta_otro || 0) + Number(row.venta_aplicaciones || 0) + Number(row.venta_alimentos || 0) + Number(row.venta_bebidas || 0);
  row.diferencia_desglose = row.total_mix - Number(row.monto_neto || 0);
  row.ticket_promedio = Number(row.visitas || 0) ? Number(row.monto_neto || 0) / Number(row.visitas) : null;
  return row;
}

function shortSalesDate(value) {
  return new Date(`${value}T12:00:00`).toLocaleDateString("es-MX", {day: "2-digit", month: "short"}).replace(".", "");
}

function renderSalesBreakdown() {
  const editable = salesBreakdownData.editable;
  const rows = salesBreakdownData.filas.map(row => calculateSalesRow(row));
  const weeklyTotal = rows.reduce((sum, row) => sum + Number(row.monto_neto || 0), 0);
  const contributing = salesBreakdownData.alcance?.sucursales_con_datos || [];
  const state = document.querySelector("#sales-edit-state");
  state.className = `badge ${editable ? "success" : "warning"}`;
  state.textContent = editable ? `Editando ${salesBreakdownData.sucursal.restaurante}` : "Consolidado · solo lectura";
  document.querySelector("#sales-scope-summary").innerHTML = editable
    ? `<div><strong>${escapeHtml(salesBreakdownData.sucursal.restaurante)} · ${escapeHtml(salesBreakdownData.sucursal.nombre)}</strong><span>Ventas diarias de la sucursal seleccionada.</span></div><strong>${money.format(weeklyTotal)}</strong>`
    : `<div><strong>Suma diaria de todas las sucursales</strong><span>${contributing.length ? `${contributing.length} sucursal${contributing.length === 1 ? "" : "es"} con ventas: ${contributing.map(item => escapeHtml(item.restaurante)).join(" · ")}` : weeklyTotal ? "Incluye todas las sucursales con ventas capturadas en esta semana." : "Ninguna sucursal tiene ventas capturadas en esta semana."}</span></div><strong>Total semanal ${money.format(weeklyTotal)}</strong>`;
  document.querySelector("#save-sales-breakdown").disabled = !editable;
  document.querySelector("#sales-payment-rows").innerHTML = rows.map((row, index) => `
    <tr><th>${shortSalesDate(row.fecha)}</th><td>${salesInput(index, "efectivo", row.efectivo, !editable)}</td><td>${salesInput(index, "dolares", row.dolares, !editable)}</td><td>${salesInput(index, "tipo_cambio", row.tipo_cambio, !editable, 'step="0.0001"')}</td><td id="sales-conversion-${index}" class="calculated">${money.format(row.conversion_usd)}</td><td>${salesInput(index, "rappi", row.rappi, !editable)}</td><td>${salesInput(index, "uber", row.uber, !editable)}</td><td>${salesInput(index, "visa", row.visa, !editable)}</td><td>${salesInput(index, "amex", row.amex, !editable)}</td><td id="sales-credit-${index}" class="calculated">${money.format(row.credito)}</td><td>${salesInput(index, "monto_neto", row.monto_neto, !editable, 'class="net-sales-input"')}</td></tr>
  `).join("");
  document.querySelector("#sales-mix-rows").innerHTML = rows.map((row, index) => `
    <tr><th>${shortSalesDate(row.fecha)}</th><td>${salesInput(index, "venta_otro", row.venta_otro, !editable)}</td><td>${salesInput(index, "venta_aplicaciones", row.venta_aplicaciones, !editable)}</td><td>${salesInput(index, "venta_alimentos", row.venta_alimentos, !editable)}</td><td>${salesInput(index, "venta_bebidas", row.venta_bebidas, !editable)}</td><td id="sales-mix-${index}" class="calculated">${money.format(row.total_mix)}</td><td id="sales-difference-${index}" class="calculated ${Math.abs(row.diferencia_desglose) > .01 ? "negative-text" : "positive-text"}">${money.format(row.diferencia_desglose)}</td><td>${salesInput(index, "faltante", row.faltante, !editable)}</td><td>${salesInput(index, "sobrante", row.sobrante, !editable)}</td><td>${salesInput(index, "visitas", row.visitas, !editable, 'step="1"')}</td><td id="sales-ticket-${index}" class="calculated">${row.ticket_promedio == null ? "—" : money.format(row.ticket_promedio)}</td></tr>
  `).join("");
  document.querySelectorAll("[data-sales-row]").forEach(input => input.oninput = handleSalesInput);
  renderSalesTotals();
}

function handleSalesInput(event) {
  const index = Number(event.target.dataset.salesRow);
  const field = event.target.dataset.salesField;
  const row = salesBreakdownData.filas[index];
  row[field] = Number(event.target.value || 0);
  if (field === "monto_neto") row.total_capturado_manual = true;
  calculateSalesRow(row);
  document.querySelector(`#sales-conversion-${index}`).textContent = money.format(row.conversion_usd);
  document.querySelector(`#sales-credit-${index}`).textContent = money.format(row.credito);
  if (field !== "monto_neto" && !row.total_capturado_manual) {
    document.querySelector(`[data-sales-row="${index}"][data-sales-field="monto_neto"]`).value = inputValue(row.monto_neto);
  }
  document.querySelector(`#sales-mix-${index}`).textContent = money.format(row.total_mix);
  const difference = document.querySelector(`#sales-difference-${index}`);
  difference.textContent = money.format(row.diferencia_desglose);
  difference.className = `calculated ${Math.abs(row.diferencia_desglose) > .01 ? "negative-text" : "positive-text"}`;
  document.querySelector(`#sales-ticket-${index}`).textContent = row.ticket_promedio == null ? "—" : money.format(row.ticket_promedio);
  renderSalesTotals();
}

function salesTotals() {
  const fields = ["efectivo", "dolares", "conversion_usd", "rappi", "uber", "visa", "amex", "credito", "monto_neto", "venta_otro", "venta_aplicaciones", "venta_alimentos", "venta_bebidas", "total_mix", "diferencia_desglose", "faltante", "sobrante", "visitas"];
  const total = Object.fromEntries(fields.map(field => [field, salesBreakdownData.filas.reduce((sum, row) => sum + Number(row[field] || 0), 0)]));
  total.tipo_cambio = total.dolares ? total.conversion_usd / total.dolares : 0;
  total.ticket_promedio = total.visitas ? total.monto_neto / total.visitas : null;
  return total;
}

function renderSalesTotals() {
  const t = salesTotals();
  document.querySelector("#sales-payment-total").innerHTML = `<tr><th>TOTAL</th><td>${money.format(t.efectivo)}</td><td>${money.format(t.dolares)}</td><td>${t.tipo_cambio ? t.tipo_cambio.toFixed(4) : "—"}</td><td>${money.format(t.conversion_usd)}</td><td>${money.format(t.rappi)}</td><td>${money.format(t.uber)}</td><td>${money.format(t.visa)}</td><td>${money.format(t.amex)}</td><td>${money.format(t.credito)}</td><td>${money.format(t.monto_neto)}</td></tr>`;
  document.querySelector("#sales-mix-total").innerHTML = `<tr><th>TOTAL</th><td>${money.format(t.venta_otro)}</td><td>${money.format(t.venta_aplicaciones)}</td><td>${money.format(t.venta_alimentos)}</td><td>${money.format(t.venta_bebidas)}</td><td>${money.format(t.total_mix)}</td><td>${money.format(t.diferencia_desglose)}</td><td>${money.format(t.faltante)}</td><td>${money.format(t.sobrante)}</td><td>${t.visitas}</td><td>${t.ticket_promedio == null ? "—" : money.format(t.ticket_promedio)}</td></tr>`;
}

async function submitSalesBreakdown(event) {
  event.preventDefault();
  if (!salesBreakdownData?.editable) return;
  const button = event.submitter;
  button.disabled = true;
  try {
    const fields = ["fecha", "efectivo", "dolares", "tipo_cambio", "rappi", "uber", "visa", "amex", "venta_otro", "venta_aplicaciones", "venta_alimentos", "venta_bebidas", "visitas", "faltante", "sobrante", "monto_neto", "total_capturado_manual"];
    const payload = {
      sucursal_id: salesBreakdownData.sucursal.id,
      actualizada_por: operator(),
      filas: salesBreakdownData.filas.map(row => Object.fromEntries(fields.map(field => [field, row[field] ?? 0]))),
      gastos: salesBreakdownData.gastos || [],
      archivo_origen: salesBreakdownData.archivo_origen || null,
    };
    const result = await api("/api/v1/finanzas/ventas-desglose", {method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload)});
    const expenseMessage = result.gastos_creados
      ? ` · ${result.gastos_creados} gastos incorporados`
      : result.gastos_existentes ? ` · ${result.gastos_existentes} gastos ya existían` : "";
    notify(`Ventas y desglose semanal guardados${expenseMessage}`);
    await loadFinanceStatement(false);
  } catch (error) {
    notify(error.message, true);
    button.disabled = false;
  }
}

async function renderProviderAdmin() {
  app.replaceChildren(document.querySelector("#catalog-template").content.cloneNode(true));
  const category = document.querySelector("#provider-category");
  category.innerHTML += (catalogs?.categorias || []).map(item =>
    `<option value="${escapeHtml(item.clave)}">${escapeHtml(item.nombre)}</option>`
  ).join("");
  const refreshSubcategories = selected => {
    const selectedCategory = (catalogs?.categorias || []).find(item => item.clave === category.value);
    const rows = (catalogs?.subcategorias || []).filter(item => item.categoria_id === selectedCategory?.id);
    document.querySelector("#provider-subcategory").innerHTML = `<option value="">Sin subcategoría</option>${rows.map(item =>
      `<option value="${escapeHtml(item.clave)}" ${item.clave === selected ? "selected" : ""}>${escapeHtml(item.nombre)}</option>`
    ).join("")}`;
  };
  category.onchange = () => refreshSubcategories("");
  refreshSubcategories("");
  document.querySelector("#provider-form").onsubmit = submitProvider;
  document.querySelector("#cancel-provider").onclick = clearProviderForm;
  document.querySelector("#new-provider").onclick = () => {
    clearProviderForm();
    document.querySelector("#provider-form").scrollIntoView({behavior: "smooth", block: "start"});
  };
  document.querySelector("#provider-search").oninput = renderProviderList;
  const importInput = document.querySelector("#provider-import-file");
  importInput.onchange = () => {
    providerImportFile = importInput.files[0] || null;
    document.querySelector("#provider-import-name").textContent = providerImportFile?.name || "Ningún archivo seleccionado";
    document.querySelector("#provider-import-preview").classList.add("hidden");
  };
  document.querySelector("#provider-import-form").onsubmit = previewProviderImport;
  document.querySelector("#subcategory-form").onsubmit = submitAccountingCatalog;
  document.querySelector("#fixed-expense-form").onsubmit = submitFixedExpense;
  document.querySelector("#own-entity-form").onsubmit = submitOwnEntity;
  document.querySelector("#own-entity-clear").onclick = () => {
    const entityForm = document.querySelector("#own-entity-form");
    entityForm.reset();
    entityForm.elements.activa.checked = true;
  };
  document.querySelector("#fixed-expense-clear").onclick = () => {
    const form = document.querySelector("#fixed-expense-form");
    form.reset();
    form.elements.activa.checked = true;
  };
  document.querySelectorAll("[data-clear-catalog]").forEach(button => {
    button.onclick = () => clearAccountingForm(button.dataset.clearCatalog);
  });
  await loadProviderAdmin();
}

async function loadProviderAdmin() {
  try {
    const [providers, quality, training, accounting, fixedExpenses, ownEntities] = await Promise.all([
      api("/api/v1/proveedores"),
      api("/api/v1/calidad-datos"),
      api("/api/v1/entrenamiento/resumen"),
      api("/api/v1/catalogos/contables"),
      api("/api/v1/gastos-fijos"),
      api("/api/v1/entidades-propias"),
    ]);
    ownEntityRows = ownEntities;
    providerAdminRows = providers;
    accountingCatalogRows = accounting;
    fixedExpenseRows = fixedExpenses;
    document.querySelector("#catalog-total").textContent = providers.filter(item => item.activo).length;
    document.querySelector("#catalog-aliases").textContent = providers.reduce((sum, item) => sum + (item.aliases?.length || 0), 0);
    document.querySelector("#catalog-issues").textContent = quality.problemas.length + Number(quality.sucursales_pendientes || 0);
    document.querySelector("#training-examples").textContent = training.ejemplos_aprobados;
    renderProviderList();
    renderQuality(quality);
    renderAccountingCatalogs();
    renderFixedExpenses();
    renderOwnEntities();
  } catch (error) {
    notify(error.message, true);
  }
}

function renderOwnEntities() {
  const list = document.querySelector("#own-entity-list");
  const form = document.querySelector("#own-entity-form");
  if (!list || !form) return;
  list.innerHTML = ownEntityRows.map(item => `
    <button class="mini-catalog-row" type="button" data-edit-entity="${item.id}"><strong>${escapeHtml(item.nombre)}</strong><small>${escapeHtml(item.rfc || "Sin RFC")} · ${item.activa ? "activa" : "inactiva"}</small></button>
  `).join("") || '<div class="empty">Aún no hay razones sociales registradas aquí; se usan las de las sucursales.</div>';
  list.querySelectorAll("[data-edit-entity]").forEach(button => button.onclick = () => {
    const item = ownEntityRows.find(row => row.id === button.dataset.editEntity);
    form.elements.nombre.value = item.nombre;
    form.elements.rfc.value = item.rfc || "";
    form.elements.activa.checked = item.activa;
  });
}

async function submitOwnEntity(event) {
  event.preventDefault();
  const form = event.target;
  const payload = {
    nombre: form.elements.nombre.value.trim(),
    rfc: form.elements.rfc.value.trim() || null,
    activa: form.elements.activa.checked,
    actualizado_por: operator(),
  };
  try {
    await api("/api/v1/entidades-propias", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
    notify("Razón social guardada");
    form.reset();
    form.elements.activa.checked = true;
    await loadProviderAdmin();
  } catch (error) {
    notify(error.message, true);
  }
}

const PERIOD_LABELS = {una_semana: "Una semana", mensual: "Mensual", bimestral: "Bimestral", personalizado: "Personalizado"};

function renderFixedExpenses() {
  const form = document.querySelector("#fixed-expense-form");
  if (!form) return;
  const providerSelect = document.querySelector("#fixed-expense-provider");
  const selected = providerSelect.value;
  providerSelect.innerHTML = '<option value="">Seleccione un proveedor</option>' + providerAdminRows.filter(item => item.activo).map(item =>
    `<option value="${item.id}" ${item.id === selected ? "selected" : ""}>${escapeHtml(item.nombre_normalizado)}</option>`
  ).join("");
  const fixedCategory = (accountingCatalogRows?.categorias || []).find(item => item.clave === "FIJOS");
  document.querySelector("#fixed-expense-subcategory").innerHTML = '<option value="">Sin subcategoría</option>' +
    (accountingCatalogRows?.subcategorias || []).filter(item => item.categoria_id === fixedCategory?.id && item.activa).map(item =>
      `<option value="${item.id}">${escapeHtml(item.nombre)}</option>`
    ).join("");
  document.querySelector("#fixed-expense-list").innerHTML = fixedExpenseRows.map(item => `
    <button class="mini-catalog-row" type="button" data-edit-fixed="${item.id}"><strong>${escapeHtml(item.proveedor)}</strong><small>${escapeHtml(item.subcategoria || "Sin subcategoría")} · ${escapeHtml(PERIOD_LABELS[item.periodicidad] || "Sin periodicidad")} · ${item.activa ? "activo" : "inactivo"}</small></button>
  `).join("") || '<div class="empty">Aún no hay proveedores de gastos fijos.</div>';
  document.querySelectorAll("[data-edit-fixed]").forEach(button => button.onclick = () => {
    const item = fixedExpenseRows.find(row => row.id === button.dataset.editFixed);
    form.elements.proveedor_id.value = item.proveedor_id;
    form.elements.subcategoria_id.value = item.subcategoria_id || "";
    form.elements.periodicidad.value = item.periodicidad || "";
    form.elements.activa.checked = item.activa;
  });
}

async function submitFixedExpense(event) {
  event.preventDefault();
  const form = event.target;
  const payload = {
    proveedor_id: form.elements.proveedor_id.value,
    subcategoria_id: form.elements.subcategoria_id.value || null,
    periodicidad: form.elements.periodicidad.value || null,
    activa: form.elements.activa.checked,
    actualizado_por: operator(),
  };
  try {
    await api("/api/v1/gastos-fijos", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
    notify("Gasto fijo guardado");
    form.reset();
    form.elements.activa.checked = true;
    catalogs = await api("/api/v1/catalogos");
    await loadProviderAdmin();
  } catch (error) {
    notify(error.message, true);
  }
}

function renderAccountingCatalogs() {
  if (!accountingCatalogRows) return;
  document.querySelector("#accounting-categories").innerHTML = accountingCatalogRows.categorias.map(item => `
    <div class="mini-catalog-row locked"><span class="catalog-key">${escapeHtml(item.clave)}</span><strong>${escapeHtml(item.nombre)}</strong><small>${item.subcategorias} subcategorías</small></div>
  `).join("");
  const categorySelect = document.querySelector("#subcategory-form [name='categoria_id']");
  const selected = categorySelect.value;
  categorySelect.innerHTML = accountingCatalogRows.categorias.filter(item => item.activa).map(item =>
    `<option value="${item.id}" ${item.id === selected ? "selected" : ""}>${escapeHtml(item.nombre)}</option>`
  ).join("");
  document.querySelector("#accounting-subcategories").innerHTML = accountingCatalogRows.subcategorias.map(item => `
    <button class="mini-catalog-row" type="button" data-edit-subcategory="${item.id}"><span class="catalog-key">${escapeHtml(item.clave)}</span><strong>${escapeHtml(item.nombre)}</strong><small>${escapeHtml(item.categoria)} · ${item.usos} usos · ${item.activa ? "activa" : "inactiva"}</small></button>
  `).join("");
  document.querySelectorAll("[data-edit-subcategory]").forEach(button => button.onclick = () => editSubcategory(button.dataset.editSubcategory));
}

function editSubcategory(id) {
  const item = accountingCatalogRows.subcategorias.find(row => row.id === id);
  const form = document.querySelector("#subcategory-form");
  form.elements.id.value = item.id;
  form.elements.categoria_id.value = item.categoria_id;
  form.elements.clave.value = item.clave;
  form.elements.nombre.value = item.nombre;
  form.elements.activa.checked = item.activa;
}

function clearAccountingForm(formId) {
  const form = document.querySelector(`#${formId}`);
  form.reset();
  form.elements.id.value = "";
  const active = form.elements.activa || form.elements.activo;
  if (active) active.checked = true;
}

async function submitAccountingCatalog(event) {
  event.preventDefault();
  const form = event.target;
  const payload = Object.fromEntries(new FormData(form));
  payload.actualizado_por = operator();
  payload.activa = form.elements.activa.checked;
  if (!payload.id) payload.id = null;
  try {
    await api("/api/v1/catalogos/subcategorias", {method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload)});
    notify("Subcategoría guardada");
    clearAccountingForm(form.id);
    catalogs = await api("/api/v1/catalogos");
    accountingCatalogRows = await api("/api/v1/catalogos/contables");
    renderAccountingCatalogs();
    const category = document.querySelector("#provider-category");
    const currentCategory = category.value;
    category.innerHTML = `<option value="">Sin regla</option>${catalogs.categorias.map(item => `<option value="${escapeHtml(item.clave)}">${escapeHtml(item.nombre)}</option>`).join("")}`;
    category.value = currentCategory;
    category.dispatchEvent(new Event("change"));
  } catch (error) {
    notify(error.message, true);
  }
}

function renderProviderList() {
  const target = document.querySelector("#provider-list");
  if (!target) return;
  const term = document.querySelector("#provider-search").value.trim().toLocaleLowerCase("es-MX");
  const rows = providerAdminRows.filter(item => {
    const haystack = [item.nombre_normalizado, item.razon_social, item.rfc, ...(item.aliases || []).map(alias => alias.alias)].join(" ").toLocaleLowerCase("es-MX");
    return !term || haystack.includes(term);
  });
  document.querySelector("#provider-list-caption").textContent = `${rows.length} de ${providerAdminRows.length} proveedores`;
  target.innerHTML = rows.length ? rows.map(item => `
    <article class="provider-row">
      <div><strong>${escapeHtml(item.nombre_normalizado)}</strong><small>${escapeHtml(item.razon_social)}${item.rfc ? ` · ${escapeHtml(item.rfc)}` : " · sin RFC"}</small></div>
      <div><span>${escapeHtml(item.categoria || "Sin regla")}</span><small>${escapeHtml(item.subcategoria || "Sin subcategoría")}</small></div>
      <div class="provider-aliases">${(item.aliases || []).length ? item.aliases.map(alias => `<span>${escapeHtml(alias.alias)}</span>`).join("") : "<small>Sin alias</small>"}</div>
      <button class="button ghost small" data-edit-provider="${item.id}">Editar</button>
    </article>`).join("") : `<div class="empty">No hay coincidencias.</div>`;
  target.querySelectorAll("[data-edit-provider]").forEach(button => {
    button.onclick = () => editProvider(button.dataset.editProvider);
  });
}

function editProvider(id) {
  const row = providerAdminRows.find(item => item.id === id);
  if (!row) return;
  const form = document.querySelector("#provider-form");
  document.querySelector("#provider-form-title").textContent = "Editar proveedor";
  form.elements.id.value = row.id;
  form.elements.rfc.value = row.rfc || "";
  form.elements.razon_social.value = row.razon_social || "";
  form.elements.nombre_normalizado.value = row.nombre_normalizado || "";
  form.elements.nombre_comercial.value = row.nombre_comercial || "";
  form.elements.categoria.value = row.categoria || "";
  form.elements.aliases.value = (row.aliases || []).map(alias => alias.alias).join(" | ");
  form.elements.activo.checked = Boolean(row.activo);
  form.elements.categoria.dispatchEvent(new Event("change"));
  form.elements.subcategoria.value = row.subcategoria || "";
  form.scrollIntoView({behavior: "smooth", block: "start"});
}

function clearProviderForm() {
  const form = document.querySelector("#provider-form");
  form.reset();
  form.elements.id.value = "";
  form.elements.activo.checked = true;
  document.querySelector("#provider-form-title").textContent = "Nuevo proveedor";
  form.elements.categoria.dispatchEvent(new Event("change"));
}

async function submitProvider(event) {
  event.preventDefault();
  const form = event.target;
  const payload = Object.fromEntries(new FormData(form));
  payload.activo = form.elements.activo.checked;
  payload.aliases = String(payload.aliases || "").split(/[|;]/).map(value => value.trim()).filter(Boolean);
  payload.actualizado_por = operator();
  ["id", "rfc", "nombre_comercial", "categoria", "subcategoria"].forEach(key => {
    if (!payload[key]) payload[key] = null;
  });
  try {
    await api("/api/v1/proveedores", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
    notify(payload.id ? "Proveedor actualizado" : "Proveedor creado");
    clearProviderForm();
    catalogs = await api("/api/v1/catalogos");
    await loadProviderAdmin();
  } catch (error) {
    notify(error.message, true);
  }
}

function renderQuality(quality) {
  const labels = {
    nombre_ocr_sin_normalizar: "Nombre con caracteres OCR pendientes",
    sin_rfc: "Proveedor sin RFC",
    sin_clasificacion: "Proveedor sin regla contable",
    categoria_inactiva: "Regla ligada a categoría inactiva",
  };
  const target = document.querySelector("#quality-list");
  const rows = [...quality.problemas];
  if (quality.sucursales_pendientes) rows.unshift({
    proveedor: `${quality.sucursales_pendientes} documento(s)`,
    problema: "sucursal_por_asignar",
  });
  labels.sucursal_por_asignar = "Sucursal pendiente; bloquea la aprobación";
  target.innerHTML = rows.length ? rows.map(item => `
    <div class="quality-row"><span class="badge warning">Pendiente</span><strong>${escapeHtml(item.proveedor)}</strong><small>${escapeHtml(labels[item.problema] || item.problema)}</small></div>
  `).join("") : `<div class="empty">El catálogo no tiene pendientes críticos.</div>`;
}

async function previewProviderImport(event) {
  event.preventDefault();
  if (!providerImportFile) return;
  const button = event.submitter;
  button.disabled = true;
  try {
    const form = new FormData();
    form.set("archivo", providerImportFile);
    form.set("importado_por", operator());
    form.set("confirmar", "false");
    const result = await api("/api/v1/proveedores/importar", {method: "POST", body: form});
    const preview = document.querySelector("#provider-import-preview");
    preview.classList.remove("hidden");
    preview.innerHTML = `<div class="import-summary"><strong>${result.filas} filas</strong><span>${result.creados} nuevas · ${result.actualizados} actualizaciones · ${result.errores} errores</span></div>
      <div class="import-rows">${result.detalle.slice(0, 12).map(item => `<div><span class="badge ${item.errores.length ? "error" : "success"}">${escapeHtml(item.accion)}</span><strong>Fila ${item.fila} · ${escapeHtml(item.datos.nombre_normalizado || "Sin nombre")}</strong><small>${escapeHtml(item.errores.join(" · ") || "Lista para importar")}</small></div>`).join("")}</div>
      <button id="confirm-provider-import" class="button primary" ${result.errores ? "disabled" : ""}>Confirmar importación</button>`;
    document.querySelector("#confirm-provider-import").onclick = confirmProviderImport;
  } catch (error) {
    notify(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function confirmProviderImport(event) {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const form = new FormData();
    form.set("archivo", providerImportFile);
    form.set("importado_por", operator());
    form.set("confirmar", "true");
    const result = await api("/api/v1/proveedores/importar", {method: "POST", body: form});
    notify(`${result.creados} proveedores creados y ${result.actualizados} actualizados`);
    catalogs = await api("/api/v1/catalogos");
    await loadProviderAdmin();
    document.querySelector("#provider-import-preview").classList.add("hidden");
  } catch (error) {
    notify(error.message, true);
    button.disabled = false;
  }
}

async function renderDashboard() {
  app.replaceChildren(document.querySelector("#dashboard-template").content.cloneNode(true));
  const panel = document.querySelector("#upload-panel");
  let uploadOpener = null;
  const toggle = (show, opener = null) => {
    if (show) uploadOpener = opener || document.activeElement;
    panel.classList.toggle("hidden", !show);
    document.body.classList.toggle("modal-open", show);
    if (show) setTimeout(() => document.querySelector("#upload-dropzone")?.focus(), 0);
    else setTimeout(() => uploadOpener?.focus(), 0);
  };
  document.querySelector("#open-upload").onclick = event => toggle(true, event.currentTarget);
  document.querySelector("#close-upload").onclick = () => toggle(false);
  document.querySelector("#cancel-upload").onclick = () => toggle(false);
  panel.onclick = event => { if (event.target === panel) toggle(false); };
  document.onkeydown = event => {
    if (panel.classList.contains("hidden")) return;
    if (event.key === "Escape") return toggle(false);
    if (event.key !== "Tab") return;
    const focusable = [...panel.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
      .filter(element => !element.disabled && element.getClientRects().length);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };
  document.querySelector("#refresh-queue").onclick = loadQueue;
  document.querySelector("#start-review").onclick = startContinuousReview;
  document.querySelector("#queue-select-all").onchange = event => {
    document.querySelectorAll(".queue-select").forEach(input => input.checked = event.target.checked);
    updateQueueSelection();
  };
  document.querySelector("#delete-selected-documents").onclick = deleteSelectedDocuments;
  const queueProvider = document.querySelector("#queue-provider");
  const reloadQueue = () => loadQueue();
  queueProvider.oninput = () => {
    clearTimeout(queueProvider.filterTimer);
    queueProvider.filterTimer = setTimeout(reloadQueue, 300);
  };
  ["#queue-type", "#queue-branch", "#queue-order"].forEach(selector => {
    document.querySelector(selector).onchange = reloadQueue;
  });
  document.querySelector("#clear-queue-filters").onclick = () => {
    document.querySelector("#queue-filters").reset();
    loadQueue();
  };
  const file = document.querySelector('input[name="archivo"]');
  const dropzone = document.querySelector("#upload-dropzone");
  const selectedFiles = new Map();
  const fileKey = item => `${item.name}:${item.size}:${item.lastModified}`;
  const syncFiles = () => {
    const transfer = new DataTransfer();
    selectedFiles.forEach(item => transfer.items.add(item));
    file.files = transfer.files;
    const count = selectedFiles.size;
    document.querySelector("#file-name").textContent = count === 1
      ? "1 documento listo"
      : count ? `${count} documentos listos` : "Puedes volver a hacer clic para sumar más archivos";
    document.querySelector("#upload-file-list").innerHTML = [...selectedFiles].map(([key, item]) => `<div class="upload-file-item"><strong title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</strong><small>${(item.size / 1048576).toFixed(1)} MB</small><button type="button" data-file-key="${escapeHtml(key)}" aria-label="Quitar ${escapeHtml(item.name)}">×</button></div>`).join("");
    document.querySelectorAll("[data-file-key]").forEach(button => button.onclick = () => { selectedFiles.delete(button.dataset.fileKey); syncFiles(); });
    const onlyFile = [...selectedFiles.values()][0];
    const isSinglePdf = count === 1 && isPdfFile(onlyFile);
    const splitControl = document.querySelector("#split-pdf");
    splitControl.closest("label").classList.toggle("hidden", !isSinglePdf);
    const currentPdfKey = isSinglePdf ? fileKey(onlyFile) : "";
    if (isSinglePdf && splitControl.dataset.fileKey !== currentPdfKey) splitControl.checked = true;
    splitControl.dataset.fileKey = currentPdfKey;
    if (!isSinglePdf) splitControl.checked = false;
    document.querySelector("#demo-data").classList.add("hidden");
  };
  const addFiles = files => { [...files].forEach(item => selectedFiles.set(fileKey(item), item)); syncFiles(); };
  file.onchange = () => addFiles(file.files);
  dropzone.onkeydown = event => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); file.click(); }
  };
  ["dragenter", "dragover"].forEach(type => dropzone.addEventListener(type, event => { event.preventDefault(); dropzone.classList.add("dragging"); }));
  ["dragleave", "drop"].forEach(type => dropzone.addEventListener(type, event => { event.preventDefault(); dropzone.classList.remove("dragging"); }));
  dropzone.addEventListener("drop", event => addFiles(event.dataTransfer.files));
  document.querySelector("#upload-form").addEventListener("reset", () => { selectedFiles.clear(); setTimeout(syncFiles, 0); });
  document.querySelector("#split-pdf").onchange = event => {
    document.querySelector("#demo-data").classList.add("hidden");
  };
  populateBranches();
  document.querySelector("#upload-form").onsubmit = submitUpload;
  document.querySelector("#discard-all-duplicates").onclick = discardAllDuplicates;
  const [, , , status] = await Promise.all([loadQueue(), loadDuplicates(), loadBatches(), loadOcrStatus()]);
  scheduleQueueRefresh.wasBusy = Boolean(status?.pendientes);
  scheduleQueueRefresh(status?.pendientes ? 3000 : 12000);
}

async function renderArchive() {
  app.replaceChildren(document.querySelector("#archive-template").content.cloneNode(true));
  document.querySelector("#archive-branch").innerHTML += (catalogs?.sucursales || [])
    .filter(item => item.clave !== "POR-ASIGNAR")
    .map(item => `<option value="${escapeHtml(item.clave)}">${escapeHtml(item.restaurante)} · ${escapeHtml(item.nombre)}</option>`).join("");
  document.querySelector("#archive-search-form").onsubmit = event => { event.preventDefault(); loadArchiveDocuments(); };
  document.querySelector("#clear-archive-search").onclick = () => {
    document.querySelector("#archive-search-form").reset();
    loadArchiveDocuments();
  };
  await loadArchiveDocuments();
}

async function loadArchiveDocuments() {
  const container = document.querySelector("#archive-results");
  const query = document.querySelector("#archive-query").value.trim();
  const status = document.querySelector("#archive-status").value;
  const params = new URLSearchParams({estado: status, limit: "20"});
  const branch = document.querySelector("#archive-branch").value;
  const dateFrom = document.querySelector("#archive-date-from").value;
  const dateTo = document.querySelector("#archive-date-to").value;
  if (query) params.set("q", query);
  if (branch) params.set("sucursal_clave", branch);
  if (dateFrom) params.set("fecha_desde", dateFrom);
  if (dateTo) params.set("fecha_hasta", dateTo);
  container.innerHTML = '<div class="empty">Buscando documentos…</div>';
  document.querySelector("#archive-results-title").textContent = query || branch || dateFrom || dateTo || status !== "aprobada"
    ? "Resultados de búsqueda" : "Últimos 20 documentos aprobados";
  try {
    const rows = await api(`/api/v1/documentos/archivo?${params}`);
    document.querySelector("#archive-result-count").textContent = `${rows.length} documento${rows.length === 1 ? "" : "s"}`;
    document.querySelector("#archive-results-caption").textContent = rows.length === 20
      ? "Mostrando los 20 resultados más recientes." : "Resultados encontrados con los filtros seleccionados.";
    if (!rows.length) {
      container.innerHTML = '<div class="empty"><strong>No encontramos documentos.</strong><br>Prueba con otra referencia, proveedor o intervalo de fechas.</div>';
      return;
    }
    container.innerHTML = rows.map(row => `<article class="archive-result">
      <div class="archive-result-reference"><span class="badge ${documentTypeClass(row.tipo_documento)}">${escapeHtml(documentType(row.tipo_documento))}</span><strong>N.º ${escapeHtml(row.numero_documento || "Sin referencia")}</strong><small>${formatDate(row.fecha)}</small></div>
      <div class="archive-result-main"><strong>${escapeHtml(row.proveedor || "Proveedor sin identificar")}</strong><span>${escapeHtml(row.archivo_nombre)}</span><small>${escapeHtml(row.restaurante)} · ${escapeHtml(row.sucursal)}</small></div>
      <div class="archive-result-total"><strong>${money.format(row.total || 0)}</strong><span class="state ${["aprobada", "aprobado"].includes(row.estado) ? "" : "pending"}">${escapeHtml(row.estado.replaceAll("_", " "))}</span></div>
      <div class="archive-result-actions"><a class="button ghost small" href="${row.archivo_url}" target="_blank">Abrir archivo</a>${row.origen === "documento_cargado" && ["requiere_revision", "aprobada"].includes(row.estado) ? `<a class="button primary small" href="#/facturas/${row.id}">${row.estado === "aprobada" ? "Ver datos" : "Revisar"}</a>` : ""}</div>
    </article>`).join("");
  } catch (error) {
    container.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
    document.querySelector("#archive-result-count").textContent = "Error";
  }
}

function catalogCategoryKey(categoryId) {
  return (catalogs?.categorias || []).find(item => item.id === categoryId)?.clave || "";
}

function learnedPeriodType(providerId, subcategoryId) {
  const rules = catalogs?.reglas_periodificacion || [];
  return rules.find(item => item.proveedor_id === providerId && item.subcategoria_id === (subcategoryId || null))?.tipo
    || rules.find(item => item.proveedor_id === providerId && !item.subcategoria_id)?.tipo
    || null;
}

function localDate(value) {
  const [year, month, day] = String(value || "").split("-").map(Number);
  return year && month && day ? new Date(Date.UTC(year, month - 1, day)) : null;
}

function dateValue(value) {
  return value.toISOString().slice(0, 10);
}

function periodBounds(referenceValue, type) {
  const reference = localDate(referenceValue) || new Date();
  const year = reference.getUTCFullYear();
  const month = reference.getUTCMonth();
  if (type === "una_semana") {
    const value = dateValue(reference);
    return [value, value];
  }
  const startMonth = type === "bimestral" ? month - 1 : month;
  const start = new Date(Date.UTC(year, startMonth, 1));
  const end = new Date(Date.UTC(year, month + 1, 0));
  return [dateValue(start), dateValue(end)];
}

function isoWeekPartsUtc(value) {
  const date = new Date(value.getTime());
  const day = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - day);
  const year = date.getUTCFullYear();
  const start = new Date(Date.UTC(year, 0, 1));
  return {year, week: Math.ceil((((date - start) / 86400000) + 1) / 7)};
}

function periodWeeks(type, fromValue, toValue) {
  const from = localDate(fromValue);
  const to = localDate(toValue);
  if (!from || !to || from > to) return [];
  const first = new Date(from.getTime());
  first.setUTCDate(first.getUTCDate() - ((first.getUTCDay() + 6) % 7));
  if (type === "una_semana") return [isoWeekPartsUtc(first)];
  const weeks = [];
  for (const cursor = new Date(first); cursor <= to; cursor.setUTCDate(cursor.getUTCDate() + 7)) {
    const sunday = new Date(cursor.getTime());
    sunday.setUTCDate(sunday.getUTCDate() + 6);
    const overlapStart = cursor > from ? cursor : from;
    const overlapEnd = sunday < to ? sunday : to;
    const days = Math.max(0, Math.floor((overlapEnd - overlapStart) / 86400000) + 1);
    if (days >= 4) weeks.push(isoWeekPartsUtc(cursor));
  }
  return weeks;
}

function updatePeriodPreview(prefix) {
  const panel = document.querySelector(`#${prefix}-periodification-panel`);
  if (!panel || panel.classList.contains("hidden")) return;
  const type = document.querySelector(`#${prefix}-period-type`).value;
  const from = document.querySelector(`#${prefix}-period-from`).value;
  const to = document.querySelector(`#${prefix}-period-to`).value;
  const weeks = periodWeeks(type, from, to);
  const preview = document.querySelector(`#${prefix}-period-preview`);
  if (!weeks.length) {
    preview.className = "period-preview error";
    preview.textContent = "El periodo debe contener al menos una semana con cuatro días.";
    return;
  }
  const cents = Math.round(Number(panel.dataset.total || 0) * 100);
  const base = Math.floor(cents / weeks.length);
  const last = base + (cents - base * weeks.length);
  preview.className = "period-preview";
  preview.textContent = `${weeks.map(item => `${item.year} · S${item.week}`).join("  ·  ")} — ${weeks.length} semana${weeks.length === 1 ? "" : "s"} — ${money.format(base / 100)} por semana${last !== base ? `; última ${money.format(last / 100)}` : ""}`;
}

function showPeriodification(prefix, {visible, referenceDate, total, providerId, subcategoryId, existing = null}) {
  const panel = document.querySelector(`#${prefix}-periodification-panel`);
  if (!panel) return;
  panel.classList.toggle("hidden", !visible);
  if (!visible) return;
  panel.dataset.total = total || 0;
  panel.dataset.referenceDate = referenceDate || new Date().toISOString().slice(0, 10);
  const signature = `${providerId || ""}:${subcategoryId || ""}`;
  const learned = learnedPeriodType(providerId, subcategoryId);
  const type = document.querySelector(`#${prefix}-period-type`);
  if (!panel.dataset.ready || (learned && panel.dataset.ruleSignature !== signature)) {
    type.value = existing?.tipo || learned || "mensual";
    const [defaultFrom, defaultTo] = periodBounds(panel.dataset.referenceDate, type.value);
    document.querySelector(`#${prefix}-period-from`).value = existing?.periodo_desde || defaultFrom;
    document.querySelector(`#${prefix}-period-to`).value = existing?.periodo_hasta || defaultTo;
    panel.dataset.ruleSignature = signature;
  }
  if (!panel.dataset.ready) {
    type.onchange = () => {
      if (type.value !== "personalizado") {
        const [from, to] = periodBounds(panel.dataset.referenceDate, type.value);
        document.querySelector(`#${prefix}-period-from`).value = from;
        document.querySelector(`#${prefix}-period-to`).value = to;
      }
      updatePeriodPreview(prefix);
      if (prefix === "invoice") trackChanges();
    };
    document.querySelector(`#${prefix}-period-from`).onchange = () => {
      updatePeriodPreview(prefix);
      if (prefix === "invoice") trackChanges();
    };
    document.querySelector(`#${prefix}-period-to`).onchange = () => {
      updatePeriodPreview(prefix);
      if (prefix === "invoice") trackChanges();
    };
    panel.dataset.ready = "true";
  }
  updatePeriodPreview(prefix);
}

function periodificationPayload(prefix) {
  const panel = document.querySelector(`#${prefix}-periodification-panel`);
  if (!panel || panel.classList.contains("hidden")) return null;
  return {
    tipo: document.querySelector(`#${prefix}-period-type`).value,
    periodo_desde: document.querySelector(`#${prefix}-period-from`).value,
    periodo_hasta: document.querySelector(`#${prefix}-period-to`).value,
  };
}

function invoicePeriodificationChanged() {
  const original = currentCase?.factura?.periodificacion || null;
  const current = periodificationPayload("invoice");
  if (!original && !current) return false;
  if (!original || !current) return true;
  return String(original.tipo) !== String(current.tipo)
    || String(original.periodo_desde) !== String(current.periodo_desde)
    || String(original.periodo_hasta) !== String(current.periodo_hasta);
}

async function renderReceipts() {
  app.replaceChildren(document.querySelector("#receipts-template").content.cloneNode(true));
  const form = document.querySelector("#receipt-form");
  const panel = document.querySelector("#receipt-form-panel");
  document.querySelector("#toggle-receipt-form").onclick = () => {
    panel.classList.remove("hidden");
    form.elements.proveedor_nombre.focus();
  };
  document.querySelector("#close-receipt-form").onclick = () => panel.classList.add("hidden");
  document.querySelector("#refresh-receipts").onclick = loadReceipts;
  form.elements.fecha_gasto.value = new Date().toISOString().slice(0, 10);
  document.querySelector("#receipt-branch").innerHTML = (catalogs?.sucursales || []).map(item =>
    `<option value="${escapeHtml(item.clave)}">${escapeHtml(item.restaurante)} · ${escapeHtml(item.nombre)}</option>`
  ).join("");
  document.querySelector("#receipt-category").innerHTML = (catalogs?.categorias || []).map(item =>
    `<option value="${item.id}">${escapeHtml(item.nombre)}</option>`
  ).join("");
  document.querySelector("#informal-provider-options").innerHTML = (catalogs?.proveedores || []).map(item =>
    `<option value="${escapeHtml(item.nombre)}"></option>`
  ).join("");

  const updateSubcategories = () => {
    const categoryId = form.elements.categoria_id.value;
    document.querySelector("#receipt-subcategory").innerHTML = optionalOptions(
      (catalogs?.subcategorias || []).filter(item => item.categoria_id === categoryId), ""
    );
    updateReceiptPeriodification();
  };
  form.elements.categoria_id.onchange = updateSubcategories;
  updateSubcategories();

  const updateSignatureRule = () => {
    const cash = form.elements.metodo_pago.value === "efectivo";
    const section = document.querySelector("#cash-signature-panel");
    section.classList.toggle("required-section", cash);
    form.elements.firma_proveedor_nombre.required = cash;
    form.elements.firma_proveedor_confirmada.required = cash;
    section.querySelector(".field-help").textContent = cash
      ? "Obligatoria: confirma la aceptación del proveedor para continuar."
      : "Opcional para este método de pago.";
  };
  form.elements.metodo_pago.onchange = updateSignatureRule;
  updateSignatureRule();

  const updateApprovalHint = () => {
    const total = Number(form.elements.total.value || 0);
    const hint = total > 300000
      ? "El máximo permitido es $300,000."
      : total > 0 ? "Este monto requiere una autorización." : "Indica el monto para calcular la autorización.";
    document.querySelector("#approval-hint").textContent = hint;
    document.querySelector("#receipt-submit-summary").textContent = "Se guardará pendiente de una autorización.";
    updateReceiptPeriodification();
  };
  form.elements.total.oninput = updateApprovalHint;

  form.elements.proveedor_nombre.onchange = () => {
    const provider = (catalogs?.proveedores || []).find(
      item => item.nombre.toLocaleLowerCase("es-MX") === form.elements.proveedor_nombre.value.trim().toLocaleLowerCase("es-MX")
    );
    if (provider) {
      if (!form.elements.proveedor_telefono.value) form.elements.proveedor_telefono.value = provider.telefono || "";
      if (!form.elements.proveedor_giro.value) form.elements.proveedor_giro.value = provider.giro || "";
    }
    updateReceiptPeriodification();
  };

  function updateReceiptPeriodification() {
    const provider = (catalogs?.proveedores || []).find(
      item => item.nombre.toLocaleLowerCase("es-MX") === form.elements.proveedor_nombre.value.trim().toLocaleLowerCase("es-MX")
    );
    showPeriodification("receipt", {
      visible: catalogCategoryKey(form.elements.categoria_id.value) === "FIJOS",
      referenceDate: form.elements.fecha_gasto.value,
      total: form.elements.total.value,
      providerId: provider?.id,
      subcategoryId: form.elements.subcategoria_id.value || null,
    });
  }
  form.elements.fecha_gasto.onchange = updateReceiptPeriodification;
  form.elements.subcategoria_id.onchange = updateReceiptPeriodification;

  form.onsubmit = submitReceipt;
  await loadReceipts();
}

async function submitReceipt(event) {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  button.textContent = "Generando…";
  try {
    const form = new FormData(event.target);
    form.set("creado_por", operator());
    if (!form.get("subcategoria_id")) form.delete("subcategoria_id");
    if (!form.get("firma_proveedor_confirmada")) form.set("firma_proveedor_confirmada", "false");
    const evidence = form.get("evidencia");
    if (evidence instanceof File && !evidence.name) form.delete("evidencia");
    const periodification = periodificationPayload("receipt");
    if (periodification) {
      form.set("periodificacion", JSON.stringify(periodification));
      form.set("recordar_periodificacion", document.querySelector("#receipt-remember-period").checked ? "true" : "false");
    }
    const receipt = await api("/api/v1/comprobantes-internos", {method: "POST", body: form});
    notify(`Recibo ${receipt.numero_documento} generado y enviado a autorización`);
    event.target.reset();
    event.target.elements.fecha_gasto.value = new Date().toISOString().slice(0, 10);
    await loadReceipts();
  } catch (error) {
    notify(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Generar recibo";
  }
}

function receiptStateLabel(state) {
  return ({
    pendiente_aprobacion: "Pendiente de autorización",
    aprobado: "Aprobado",
    rechazado: "Rechazado",
    sustituido: "Sustituido por CFDI"
  })[state] || state.replaceAll("_", " ");
}

async function loadReceipts() {
  const container = document.querySelector("#receipts-list");
  if (!container) return;
  container.innerHTML = '<div class="empty">Cargando…</div>';
  try {
    const rows = await api("/api/v1/comprobantes-internos?limit=50");
    if (!rows.length) {
      container.innerHTML = '<div class="empty"><strong>No hay comprobantes internos.</strong><br>Genera el primero desde esta pantalla.</div>';
      return;
    }
    container.innerHTML = rows.map(row => {
      const pending = row.estado === "pendiente_aprobacion";
      return `<article class="receipt-card">
        <div class="receipt-card-main">
          <div class="receipt-folio"><strong>N.º ${escapeHtml(row.numero_documento)}</strong><span class="badge ${row.estado === "aprobado" ? "success" : row.estado === "rechazado" ? "error" : "warning"}">${escapeHtml(receiptStateLabel(row.estado))}</span></div>
          <h3>${escapeHtml(row.proveedor)}</h3>
          <p>${escapeHtml(row.concepto)}</p>
          <small>${escapeHtml(row.folio)} · ${formatDate(row.fecha_gasto)} · ${escapeHtml(row.restaurante)} · ${escapeHtml(row.categoria)} · ${escapeHtml(row.metodo_pago)}</small>
        </div>
        <div class="receipt-card-total"><strong>${money.format(row.total)}</strong><span>${row.estado_fiscal === "con_cfdi" ? "Con CFDI" : "No deducible"}</span></div>
        <div class="receipt-card-actions">
          <a class="button ghost small" href="/api/v1/comprobantes-internos/${row.id}/pdf" target="_blank">Ver PDF</a>
          ${row.evidencia_nombre ? `<a class="button ghost small" href="/api/v1/comprobantes-internos/${row.id}/evidencia" target="_blank">Evidencia</a>` : ""}
          ${pending ? `<button class="button primary small approve-receipt" data-id="${row.id}">Autorizar</button><button class="button danger ghost small reject-receipt" data-id="${row.id}">Rechazar</button>` : ""}
          ${row.estado === "aprobado" ? `<button class="button ghost small replace-receipt" data-id="${row.id}">Vincular CFDI</button>` : ""}
        </div>
      </article>`;
    }).join("");
    container.querySelectorAll(".approve-receipt").forEach(button => button.onclick = () => approveReceipt(button.dataset.id));
    container.querySelectorAll(".reject-receipt").forEach(button => button.onclick = () => rejectReceipt(button.dataset.id));
    container.querySelectorAll(".replace-receipt").forEach(button => button.onclick = () => replaceReceipt(button.dataset.id));
  } catch (error) {
    container.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

async function approveReceipt(id) {
  try {
    const receipt = await api(`/api/v1/comprobantes-internos/${id}/aprobar`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({autorizada_por: operator()})
    });
    notify(receipt.estado === "aprobado" ? "Comprobante aprobado y publicado en Analytics" : "Primera autorización registrada");
    await loadReceipts();
  } catch (error) { notify(error.message, true); }
}

async function rejectReceipt(id) {
  const reason = window.prompt("Motivo del rechazo:");
  if (!reason) return;
  try {
    await api(`/api/v1/comprobantes-internos/${id}/rechazar`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({rechazada_por: operator(), motivo: reason})
    });
    notify("Comprobante rechazado");
    await loadReceipts();
  } catch (error) { notify(error.message, true); }
}

async function replaceReceipt(id) {
  const invoiceId = window.prompt("ID de la factura final (CFDI) que sustituye este comprobante:");
  if (!invoiceId) return;
  try {
    await api(`/api/v1/comprobantes-internos/${id}/sustituir`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({factura_final_id: invoiceId.trim()})
    });
    notify("CFDI vinculado; el recibo dejó de sumar por separado");
    await loadReceipts();
  } catch (error) { notify(error.message, true); }
}

async function renderAnalyticsDashboard() {
  app.replaceChildren(document.querySelector("#analytics-template").content.cloneNode(true));
  try {
    const scope = document.querySelector("#analytics-scope");
    scope.onchange = () => renderAnalyticsScope(scope.value);
    const now = new Date();
    const iso = isoWeekParts(now);
    document.querySelector("#analytics-iso-year").value = iso.year;
    document.querySelector("#analytics-iso-week").value = iso.week;
    document.querySelector("#analytics-date-from").value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
    document.querySelector("#analytics-date-to").value = localDateValue(now);
    document.querySelector("#analytics-period-mode").onchange = toggleAnalyticsPeriodFields;
    document.querySelector("#analytics-apply").onclick = refreshAnalyticsDashboard;
    const analyticsCategory = document.querySelector("#analytics-category");
    analyticsCategory.innerHTML = '<option value="">Todas</option>' + (catalogs?.categorias || []).map(item =>
      `<option value="${escapeHtml(item.nombre)}">${escapeHtml(item.nombre)}</option>`
    ).join("");
    analyticsCategory.onchange = refreshAnalyticsDashboard;
    toggleAnalyticsPeriodFields();
    await refreshAnalyticsDashboard();
  } catch (error) {
    document.querySelector("#category-chart").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

function isoWeekParts(value) {
  const date = new Date(Date.UTC(value.getFullYear(), value.getMonth(), value.getDate()));
  const day = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  return {
    year: date.getUTCFullYear(),
    week: Math.ceil((((date - yearStart) / 86400000) + 1) / 7)
  };
}

function localDateValue(value) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function toggleAnalyticsPeriodFields() {
  const range = document.querySelector("#analytics-period-mode").value === "range";
  document.querySelector("#analytics-iso-fields").classList.toggle("hidden", range);
  document.querySelector("#analytics-date-fields").classList.toggle("hidden", !range);
}

function analyticsFilterQuery() {
  const params = new URLSearchParams();
  if (document.querySelector("#analytics-period-mode").value === "iso") {
    params.set("anio_iso", document.querySelector("#analytics-iso-year").value);
    params.set("semana_iso", document.querySelector("#analytics-iso-week").value);
  } else {
    params.set("fecha_desde", document.querySelector("#analytics-date-from").value);
    params.set("fecha_hasta", document.querySelector("#analytics-date-to").value);
  }
  const category = document.querySelector("#analytics-category").value;
  if (category) params.set("categoria", category);
  return params;
}

function analyticsFilterLabel() {
  const categorySelect = document.querySelector("#analytics-category");
  const category = categorySelect.value ? ` · ${categorySelect.options[categorySelect.selectedIndex].text}` : " · Todas las categorías";
  if (document.querySelector("#analytics-period-mode").value === "iso") {
    return `Semana ISO ${document.querySelector("#analytics-iso-week").value} de ${document.querySelector("#analytics-iso-year").value}${category}`;
  }
  return `${document.querySelector("#analytics-date-from").value} a ${document.querySelector("#analytics-date-to").value}${category}`;
}

async function refreshAnalyticsDashboard() {
  const button = document.querySelector("#analytics-apply");
  button.disabled = true;
  button.textContent = "Aplicando…";
  try {
    const query = analyticsFilterQuery();
    analyticsData = await api(`/api/v1/analytics/dashboard?${query}`);
    document.querySelector("#analytics-export").href = `/api/v1/analytics/exportar.csv?${query}`;
    renderAnalyticsScope(document.querySelector("#analytics-scope").value);
  } catch (error) {
    notify(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "Aplicar filtros";
  }
}

function renderAnalyticsScope(scope) {
  const data = analyticsData[scope];
  const pending = analyticsData.pendiente;
  const preliminary = scope === "preliminar";
  document.querySelector("#analysis-total").textContent = money.format(data.total || 0);
  document.querySelector("#analysis-invoices").textContent = data.facturas;
  document.querySelector("#analysis-ticket").textContent = money.format(data.ticket_promedio || 0);
  document.querySelector("#analysis-pending").textContent = pending.facturas;
  const note = document.querySelector("#analytics-scope-note");
  note.classList.toggle("preliminary", preliminary);
  const scopeText = preliminary
    ? `Vista preliminar: incluye ${pending.facturas} factura${pending.facturas === 1 ? "" : "s"} pendiente${pending.facturas === 1 ? "" : "s"} por ${money.format(pending.total || 0)}. No representa todavía una cifra contable final.`
    : "Vista contable: muestra facturas, tickets, notas, remisiones y comprobantes internos aprobados mediante revisión humana.";
  note.textContent = `${analyticsFilterLabel()}. ${scopeText}`;
  renderBarChart("#category-chart", data.categorias);
  renderBarChart("#provider-chart", data.proveedores);
  renderDailyChart(data.tendencia_diaria);
  renderAnalyticsRows(data.recientes);
}

function renderBarChart(selector, rows) {
  const container = document.querySelector(selector);
  if (!rows.length) {
    container.innerHTML = '<div class="empty">Todavía no hay movimientos en esta vista.</div>';
    return;
  }
  const maximum = Math.max(...rows.map(row => Number(row.total || 0)), 1);
  container.innerHTML = rows.map(row => `
    <div class="bar-row">
      <div class="bar-label"><strong>${escapeHtml(row.nombre)}</strong><small>${row.facturas} movimiento${row.facturas === 1 ? "" : "s"}</small></div>
      <div class="bar-track" aria-label="${escapeHtml(row.nombre)}: ${money.format(row.total || 0)}"><span class="bar-fill" style="width:${Math.max(1, Number(row.total || 0) * 100 / maximum)}%"></span></div>
      <div class="bar-value">${money.format(row.total || 0)}</div>
    </div>`).join("");
}

function renderDailyChart(rows) {
  const container = document.querySelector("#daily-chart");
  if (!rows.length) {
    container.innerHTML = '<div class="empty">No hay fechas disponibles para construir la tendencia.</div>';
    return;
  }
  const width = 900;
  const height = 230;
  const left = 64;
  const right = 22;
  const top = 25;
  const bottom = 45;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const maximum = Math.max(...rows.map(row => Number(row.total || 0)), 1);
  const x = index => rows.length === 1 ? left + plotWidth / 2 : left + index * plotWidth / (rows.length - 1);
  const y = value => top + plotHeight - Number(value || 0) * plotHeight / maximum;
  const points = rows.map((row, index) => `${x(index)},${y(row.total)}`).join(" ");
  const areaPoints = `${left},${top + plotHeight} ${points} ${width - right},${top + plotHeight}`;
  const grid = [0, .25, .5, .75, 1].map(ratio => {
    const gridY = top + plotHeight - ratio * plotHeight;
    return `<line class="grid-line" x1="${left}" y1="${gridY}" x2="${width - right}" y2="${gridY}"></line><text x="${left - 8}" y="${gridY + 4}" text-anchor="end">${compactMoney(maximum * ratio)}</text>`;
  }).join("");
  const marks = rows.map((row, index) => `
    <circle class="trend-point" cx="${x(index)}" cy="${y(row.total)}" r="5"><title>${formatDate(row.fecha)} · ${money.format(row.total || 0)}</title></circle>
    <text class="value-label" x="${x(index)}" y="${Math.max(14, y(row.total) - 11)}" text-anchor="middle">${compactMoney(row.total)}</text>
    <text x="${x(index)}" y="${height - 17}" text-anchor="middle">${formatDate(row.fecha)}</text>`).join("");
  container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Tendencia diaria de gasto">${grid}<line class="axis" x1="${left}" y1="${top + plotHeight}" x2="${width - right}" y2="${top + plotHeight}"></line><polygon class="trend-area" points="${areaPoints}"></polygon><polyline class="trend-line" points="${points}"></polyline>${marks}</svg>`;
}

function compactMoney(value) {
  return new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN", notation: "compact", maximumFractionDigits: 1 }).format(value || 0);
}

function formatDate(value) {
  if (!value) return "Sin fecha";
  return new Date(`${value}T00:00:00`).toLocaleDateString("es-MX", { day: "2-digit", month: "short" });
}

function renderAnalyticsRows(rows) {
  const body = document.querySelector("#analytics-rows");
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="7"><div class="empty">No hay movimientos en esta vista.</div></td></tr>';
    return;
  }
  body.innerHTML = rows.map(row => `
    <tr>
      <td>${formatDate(row.fecha)}</td>
      <td>${escapeHtml(row.proveedor || "Proveedor sin identificar")}</td>
      <td>${escapeHtml(row.categoria || "Sin categoría")}</td>
      <td>${escapeHtml(row.restaurante || "Por asignar")}</td>
      <td><span class="state ${row.estado === "aprobada" ? "" : "pending"}">${row.tipo_documento === "comprobante_interno" ? "Recibo interno" : row.estado === "aprobada" ? `${documentType(row.tipo_documento)} aprobado` : "En revisión"}</span></td>
      <td class="numeric">${row.total == null ? "—" : money.format(row.total)}</td>
      <td>${row.tipo_documento === "comprobante_interno" ? "—" : `<a class="button ghost small" href="#/facturas/${row.documento_origen_id || row.movimiento_id}">Editar</a>`}</td>
    </tr>`).join("");
}

function populateBranches() {
  const select = document.querySelector("#upload-branch");
  select.innerHTML = (catalogs?.sucursales || []).map(item =>
    `<option value="${escapeHtml(item.clave)}">${escapeHtml(item.restaurante)} · ${escapeHtml(item.nombre)}</option>`
  ).join("");
  const queueBranch = document.querySelector("#queue-branch");
  if (queueBranch) {
    queueBranch.innerHTML = '<option value="">Todas</option>' + (catalogs?.sucursales || [])
      .filter(item => item.clave !== "POR-ASIGNAR")
      .map(item => `<option value="${escapeHtml(item.clave)}">${escapeHtml(item.restaurante)} · ${escapeHtml(item.nombre)}</option>`)
      .join("");
  }
}

async function loadQueue(options = {}) {
  const container = document.querySelector("#queue");
  if (!container) return;
  // En las actualizaciones automáticas se conserva lo que la persona ya marcó.
  const keepSelected = options.keepSelection === true
    ? new Set([...container.querySelectorAll(".queue-select:checked")].map(input => input.value))
    : new Set();
  // Solo se muestra "Cargando…" la primera vez; en las actualizaciones
  // automáticas la lista no debe parpadear.
  if (!container.children.length) container.innerHTML = '<div class="empty">Cargando…</div>';
  try {
    const query = new URLSearchParams();
    const provider = document.querySelector("#queue-provider")?.value.trim();
    const type = document.querySelector("#queue-type")?.value;
    const branch = document.querySelector("#queue-branch")?.value;
    const order = document.querySelector("#queue-order")?.value;
    if (provider) query.set("proveedor", provider);
    if (type) query.set("tipo_documento", type);
    if (branch) query.set("sucursal_clave", branch);
    if (order) query.set("orden", order);
    reviewQueueQuery = query.toString();
    const [rows, summary] = await Promise.all([
      api(`/api/v1/revision?${query}`),
      api(`/api/v1/revision/resumen?${query}`),
    ]);
    document.querySelector("#metric-pending").textContent = summary.total;
    document.querySelector("#metric-invoices").textContent = summary.facturas;
    document.querySelector("#metric-payments").textContent = summary.pagos;
    document.querySelector("#metric-other").textContent = summary.otros;
    document.querySelector("#queue-caption").textContent = summary.total
      ? `${summary.total} documento${summary.total === 1 ? "" : "s"} por atender${summary.total > rows.length ? ` · mostrando ${rows.length}` : ""}`
      : "No hay trabajo pendiente";
    firstReviewId = rows[0]?.id || null;
    const startButton = document.querySelector("#start-review");
    if (startButton) startButton.disabled = !firstReviewId;
    if (!rows.length) {
      document.querySelector("#queue-selection-bar").classList.add("hidden");
      container.innerHTML = '<div class="empty"><strong>La bandeja está al día.</strong><br>Sube una factura para continuar.</div>';
      return;
    }
    document.querySelector("#queue-selection-bar").classList.remove("hidden");
    document.querySelector("#queue-select-all").checked = false;
    container.innerHTML = rows.map(row => `
      <article class="queue-item" data-id="${row.id}" tabindex="0">
        <label class="queue-check" aria-label="Seleccionar ${escapeHtml(row.archivo_nombre)}"><input class="queue-select" type="checkbox" value="${row.id}"></label>
        <span class="priority ${row.validaciones_fallidas ? "error" : ""}"></span>
        <div class="queue-main"><strong>${escapeHtml(row.proveedor || "Proveedor sin identificar")}</strong><small>${row.folio ? `N.º ${escapeHtml(row.folio)} · ` : ""}${escapeHtml(row.archivo_nombre)}${row.paginas_adicionales ? ` · <span class="pages-badge">+${row.paginas_adicionales} pág.</span>` : ""}${row.campos_dudosos ? ` · <span class="doubt-badge">${row.campos_dudosos} por revisar</span>` : ""}</small></div>
        <div class="queue-cell">${escapeHtml(row.sucursal)}<small>${escapeHtml(row.restaurante)}</small></div>
        <div class="queue-cell"><span class="badge ${documentTypeClass(row.tipo_documento)}">${documentType(row.tipo_documento)}</span><small>${isExpenseDocumentType(row.tipo_documento) ? (row.validaciones_fallidas ? `${row.validaciones_fallidas} validaciones` : "Lista para registrar gasto") : "Fuera del flujo de gasto"}</small></div>
        <div class="queue-total">${row.total == null ? "—" : money.format(row.total)}</div>
      </article>`).join("");
    container.querySelectorAll(".queue-item").forEach(item => {
      item.onclick = event => {
        if (!event.target.closest(".queue-check")) {
          reviewFlowActive = false;
          location.hash = `#/facturas/${item.dataset.id}`;
        }
      };
      item.onkeydown = event => { if (event.key === "Enter") item.click(); };
    });
    container.querySelectorAll(".queue-select").forEach(input => {
      input.checked = keepSelected.has(input.value);
      input.onclick = event => event.stopPropagation();
      input.onchange = updateQueueSelection;
    });
    updateQueueSelection();
  } catch (error) {
    container.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

function startContinuousReview() {
  if (!firstReviewId) return;
  reviewFlowActive = true;
  location.hash = `#/facturas/${firstReviewId}`;
}

async function continueReviewFlow() {
  if (!reviewFlowActive) {
    location.hash = "#/bandeja";
    return;
  }
  const query = new URLSearchParams(reviewQueueQuery);
  query.set("limit", "1");
  query.set("offset", "0");
  const rows = await api(`/api/v1/revision?${query}`);
  if (rows.length) {
    location.hash = `#/facturas/${rows[0].id}`;
    return;
  }
  reviewFlowActive = false;
  notify("Revisión terminada: no quedan documentos con estos filtros");
  location.hash = "#/bandeja";
}

function updateQueueSelection() {
  const inputs = [...document.querySelectorAll(".queue-select")];
  const selected = inputs.filter(input => input.checked);
  const count = document.querySelector("#queue-selected-count");
  const button = document.querySelector("#delete-selected-documents");
  if (!count || !button) return;
  count.textContent = `${selected.length} seleccionado${selected.length === 1 ? "" : "s"}`;
  button.disabled = !selected.length;
  const all = document.querySelector("#queue-select-all");
  all.checked = Boolean(inputs.length) && selected.length === inputs.length;
  all.indeterminate = selected.length > 0 && selected.length < inputs.length;
}

async function deleteSelectedDocuments() {
  const ids = [...document.querySelectorAll(".queue-select:checked")].map(input => input.value);
  if (!ids.length) return;
  const confirmed = window.confirm(`Se eliminarán ${ids.length} documento${ids.length === 1 ? "" : "s"} y sus archivos. Esta acción no se puede deshacer. ¿Continuar?`);
  if (!confirmed) return;
  const button = document.querySelector("#delete-selected-documents");
  button.disabled = true;
  try {
    const result = await api("/api/v1/facturas", {
      method: "DELETE",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({factura_ids: ids, eliminado_por: operator()}),
    });
    notify(`${result.eliminados} documentos eliminados`);
    await Promise.all([loadQueue(), loadBatches()]);
  } catch (error) {
    notify(error.message, true);
    button.disabled = false;
  }
}

function documentType(value) {
  const labels = {
    factura_fiscal: "Factura",
    ticket_compra: "Ticket de compra",
    nota_venta: "Nota de venta",
    remision: "Remisión",
    nota_credito: "Nota de crédito",
    transferencia_bancaria: "Transferencia",
    pago_servicio: "Pago de servicio",
    sipare_imss: "SIPARE / IMSS",
    comprobante_pago: "Comprobante de pago",
    comprobante_interno: "Comprobante interno",
    recibo: "Recibo",
    desconocido: "Desconocido"
  };
  return labels[value] || "Sin clasificar";
}

function isExpenseDocumentType(value) {
  return ["factura_fiscal", "ticket_compra", "nota_venta", "remision", "recibo", "comprobante_interno"].includes(value);
}

function documentTypeClass(value) {
  if (isExpenseDocumentType(value)) return "success";
  if (value === "comprobante_pago") return "warning";
  return "error";
}

async function loadBatches() {
  const container = document.querySelector("#batches");
  if (!container) return;
  try {
    const rows = await api("/api/v1/lotes?limit=5");
    if (!rows.length) {
      container.innerHTML = '<div class="empty">Todavía no hay PDFs multipágina.</div>';
      return;
    }
    container.innerHTML = rows.map(row => {
      const ready = row.revision + row.aprobadas + row.rechazadas + row.errores;
      const percent = row.total_paginas ? Math.round(ready * 100 / row.total_paginas) : 0;
      return `<article class="batch-item">
        <div class="batch-main"><strong>${escapeHtml(row.archivo_original_nombre)}</strong><small>${escapeHtml(row.restaurante)} · ${escapeHtml(row.sucursal)}</small></div>
        <div><div class="progress-track"><i style="width:${percent}%"></i></div><div class="progress-label"><span>${percent}% leído</span><span>${row.procesando} procesando</span></div></div>
        <div class="batch-count"><strong>${row.total_paginas} páginas</strong><br><span>${row.recibidas} por leer · ${row.revision} por revisar${row.errores ? ` · ${row.errores} error` : ""}</span></div>
        <div class="batch-actions">
          ${row.estado === "cancelado" ? `<span class="badge error">Cancelado</span><button class="button danger small delete-batch" data-id="${row.id}">Eliminar lote</button>` : (row.recibidas || row.errores) ? `<button class="button primary small process-batch" data-id="${row.id}">${row.errores ? "Reintentar" : "Procesar"}</button>` : '<span class="badge success">OCR completo</span>'}
          ${row.estado !== "cancelado" && (row.recibidas || row.procesando) ? `<button class="button danger small cancel-batch" data-id="${row.id}">Detener</button>` : ""}
        </div>
      </article>`;
    }).join("");
    container.querySelectorAll(".process-batch").forEach(button => button.onclick = async () => {
      button.disabled = true;
      try {
        await api(`/api/v1/lotes/${button.dataset.id}/procesar`, {method: "POST"});
        notify("Procesamiento OCR iniciado");
        scheduleBatchRefresh();
      } catch (error) { notify(error.message, true); button.disabled = false; }
    });
    container.querySelectorAll(".cancel-batch").forEach(button => button.onclick = async () => {
      if (!window.confirm("Se detendrá el lote y los documentos pendientes saldrán del procesamiento. ¿Continuar?")) return;
      button.disabled = true;
      try {
        const result = await api(`/api/v1/lotes/${button.dataset.id}/cancelar`, {
          method: "POST", headers: {"Content-Type":"application/json"},
          body: JSON.stringify({cancelado_por: operator()}),
        });
        notify(`Procesamiento detenido: ${result.canceladas} documentos cancelados`);
        await Promise.all([loadBatches(), loadQueue()]);
      } catch (error) { notify(error.message, true); button.disabled = false; }
    });
    container.querySelectorAll(".delete-batch").forEach(button => button.onclick = async () => {
      if (!window.confirm("Se eliminarán todos los documentos y archivos de este lote. Esta acción no se puede deshacer. ¿Continuar?")) return;
      button.disabled = true;
      try {
        const result = await api(`/api/v1/lotes/${button.dataset.id}`, {
          method: "DELETE", headers: {"Content-Type":"application/json"},
          body: JSON.stringify({eliminado_por: operator()}),
        });
        notify(`${result.eliminados} documentos del lote eliminados`);
        await Promise.all([loadBatches(), loadQueue()]);
      } catch (error) { notify(error.message, true); button.disabled = false; }
    });
    if (rows.some(row => row.recibidas || row.procesando)) scheduleBatchRefresh();
  } catch (error) {
    container.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

function scheduleBatchRefresh() {
  clearTimeout(loadBatches.timer);
  loadBatches.timer = setTimeout(() => {
    if (document.querySelector("#batches")) {
      loadBatches();
      loadQueue();
      loadOcrStatus();
    }
  }, 3000);
}

// Un solo ciclo mientras la bandeja está en pantalla. Consultar el estado de la
// lectura es barato, así que se hace siempre (también detecta lo que suben otras
// personas); la lista completa solo se vuelve a pedir mientras haya documentos
// leyéndose y una vez más cuando terminan.
function scheduleQueueRefresh(delay = 3000) {
  clearTimeout(loadQueue.timer);
  loadQueue.timer = setTimeout(async () => {
    if (!document.querySelector("#queue")) return;
    const status = await loadOcrStatus();
    const busy = Boolean(status?.pendientes);
    if (busy || scheduleQueueRefresh.wasBusy) {
      await Promise.all([loadQueue({ keepSelection: true }), loadDuplicates()]);
    }
    scheduleQueueRefresh.wasBusy = busy;
    scheduleQueueRefresh(busy ? 3000 : 12000);
  }, delay);
}

function formatEta(seconds) {
  if (seconds < 60) return "menos de 1 min";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h${minutes % 60 ? ` ${minutes % 60} min` : ""}`;
}

let ocrNoWorkerSince = null;

async function loadOcrStatus() {
  const box = document.querySelector("#ocr-status");
  if (!box) return null;
  try {
    const status = await api("/api/v1/cola-ocr");
    const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;
    const waiting = status.en_cola + status.reintentando;
    let tone = "";
    let html = "";
    if (status.pendientes && !status.workers_activos) {
      ocrNoWorkerSince ??= Date.now();
      tone = "warning";
      html = Date.now() - ocrNoWorkerSince < 60000
        ? `<strong>Iniciando el lector de documentos…</strong><span>${plural(status.pendientes, "documento espera", "documentos esperan")} y empezarán en unos segundos.</span>`
        : `<strong>No hay un lector de documentos activo</strong><span>${plural(status.pendientes, "documento espera", "documentos esperan")}. Verifique que el servicio de lectura esté en ejecución (<code>python -m app.worker_cli</code>).</span>`;
    } else if (status.pendientes) {
      ocrNoWorkerSince = null;
      const parts = [
        `${status.procesando} en lectura`,
        `${waiting} en espera${status.reintentando ? ` (${status.reintentando} reintentando)` : ""}`,
      ];
      if (status.eta_segundos) parts.push(`termina en ≈ ${formatEta(status.eta_segundos)}`);
      html = `<i class="pulse" aria-hidden="true"></i><strong>Leyendo documentos</strong><span>${parts.join(" · ")}</span>`;
    } else if (status.fallidos_24h) {
      ocrNoWorkerSince = null;
      tone = "error";
      html = `<strong>${plural(status.fallidos_24h, "documento no pudo leerse", "documentos no pudieron leerse")} en las últimas 24 h</strong><span>Revise los lotes para reintentarlos o elimínelos.</span>`;
    } else {
      ocrNoWorkerSince = null;
    }
    box.className = `ocr-status ${tone}${html ? "" : " hidden"}`;
    box.innerHTML = html;
    return status;
  } catch (error) {
    return null;
  }
}

async function loadDuplicates() {
  const panel = document.querySelector("#duplicates-panel");
  const container = document.querySelector("#duplicates");
  if (!panel || !container) return;
  try {
    const rows = await api("/api/v1/duplicados");
    panel.classList.toggle("hidden", !rows.length);
    panel.dataset.ids = rows.map(row => row.id).join(",");
    if (!rows.length) {
      container.innerHTML = "";
      return;
    }
    container.innerHTML = rows.map(row => `
      <article class="duplicate-item">
        <div class="duplicate-comparison">
          <div class="duplicate-file suspect">
            <span>ARCHIVO DETECTADO</span>
            <strong>${escapeHtml(row.archivo_duplicado)}</strong>
            <a class="button ghost small" href="/api/v1/duplicados/${row.id}/archivo" target="_blank" rel="noopener">Abrir detectado ↗</a>
          </div>
          <div class="duplicate-link" aria-hidden="true">↔</div>
          <div class="duplicate-file original">
            <span>ARCHIVO RELACIONADO</span>
            <strong>${escapeHtml(row.archivo_original)}</strong>
            <a class="button ghost small" href="/api/v1/facturas/${row.factura_original_id}/archivo" target="_blank" rel="noopener">Abrir relacionado ↗</a>
          </div>
        </div>
        <div class="duplicate-reason"><strong>${row.criterio === "uuid_fiscal" ? "Mismo UUID fiscal" : "Contenido idéntico"}</strong><small>${row.criterio === "uuid_fiscal" ? `UUID: ${escapeHtml(row.valor_coincidente)}` : "Coincidencia exacta del archivo"}</small></div>
        <div><strong>${escapeHtml(row.proveedor || "Proveedor por identificar")}</strong><small>${row.folio ? `Folio ${escapeHtml(row.folio)} · ` : ""}${escapeHtml(row.sucursal)}</small></div>
        <div class="duplicate-total">${row.total == null ? "—" : money.format(row.total)}</div>
        <button class="button danger small discard-duplicate" data-id="${row.id}" type="button">Eliminar duplicado</button>
      </article>`).join("");
    container.querySelectorAll(".discard-duplicate").forEach(button => {
      button.onclick = () => discardDuplicates([button.dataset.id]);
    });
  } catch (error) {
    panel.classList.remove("hidden");
    container.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
  }
}

async function discardDuplicates(ids) {
  if (!ids.length || !confirm(`Se eliminarán ${ids.length} archivo${ids.length === 1 ? "" : "s"} duplicado${ids.length === 1 ? "" : "s"}. El original se conservará. ¿Continuar?`)) return;
  const result = await api("/api/v1/duplicados/descartar", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({duplicado_ids: ids, descartado_por: operator()}),
  });
  notify(`${result.descartados} duplicado${result.descartados === 1 ? "" : "s"} descartado${result.descartados === 1 ? "" : "s"}`);
  await Promise.all([loadDuplicates(), loadQueue()]);
}

function discardAllDuplicates() {
  const ids = (document.querySelector("#duplicates-panel")?.dataset.ids || "").split(",").filter(Boolean);
  return discardDuplicates(ids);
}

async function submitUpload(event) {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  button.textContent = "Procesando…";
  try {
    const form = new FormData(event.target);
    const selectedFile = form.get("archivo");
    const selectedFiles = event.target.elements.archivo.files;
    const splitPdf = isPdfFile(selectedFile) && document.querySelector("#split-pdf").checked;
    if (selectedFiles.length > 1) {
      const bulk = new FormData();
      [...selectedFiles].forEach(file => bulk.append("archivos", file));
      bulk.set("sucursal_clave", form.get("sucursal_clave"));
      bulk.set("creada_por", operator());
      const result = await api("/api/v1/documentos/carga-masiva", { method: "POST", body: bulk });
      notify(`${result.creados.length} documentos cargados y en cola de lectura${result.duplicados.length ? ` · ${result.duplicados.length} duplicados omitidos` : ""}${result.errores.length ? ` · ${result.errores.length} con error` : ""}`, result.errores.length > 0 && !result.creados.length);
      loadOcrStatus();
      event.target.reset();
      document.querySelector("#upload-panel").classList.add("hidden");
      document.body.classList.remove("modal-open");
      scheduleQueueRefresh();
      button.disabled = false;
      button.textContent = "Cargar y procesar";
      return;
    }
    if (splitPdf) {
      form.set("creada_por", operator());
      ["proveedor", "fecha_emision", "subtotal", "iva", "total"].forEach(key => form.delete(key));
      const batch = await api("/api/v1/lotes", { method: "POST", body: form });
      await api(`/api/v1/lotes/${batch.id}/procesar`, { method: "POST" });
      notify(`${batch.facturas_creadas} facturas creadas desde ${batch.total_paginas} páginas`);
      event.target.reset();
      document.querySelector("#upload-panel").classList.add("hidden");
      document.body.classList.remove("modal-open");
      await loadBatches();
      scheduleBatchRefresh();
      button.disabled = false;
      button.textContent = "Cargar y procesar";
      return;
    }
    if (isPdfFile(selectedFile)) {
      form.set("permitir_pdf_multipagina", "true");
    }
    form.set("creada_por", operator());
    ["proveedor", "fecha_emision", "subtotal", "iva", "total"].forEach(key => form.delete(key));
    const created = await api("/api/v1/facturas", { method: "POST", body: form });
    await api(`/api/v1/facturas/${created.id}/procesar-ocr`, { method: "POST" });
    const isXml = selectedFile?.name?.toLowerCase().endsWith(".xml");
    notify(isXml ? "XML fiscal cargado; en cola de lectura" : "Documento cargado; en cola de lectura");
    loadOcrStatus();
    document.querySelector("#upload-panel").classList.add("hidden");
    document.body.classList.remove("modal-open");
    scheduleQueueRefresh();
  } catch (error) {
    notify(error.message, true);
    button.disabled = false;
    button.textContent = "Cargar y procesar";
  }
}

async function renderReview(id) {
  app.replaceChildren(document.querySelector("#review-template").content.cloneNode(true));
  try {
    currentCase = await api(`/api/v1/facturas/${id}/expediente`);
    const item = currentCase.factura;
    const editingApproved = item.estado === "aprobada";
    if (editingApproved) {
      const back = document.querySelector(".review-header .back-link");
      back.href = "#/analytics";
      back.textContent = "← Analytics";
      document.querySelector(".review-title .eyebrow").textContent = "EDICIÓN DE FACTURA APROBADA";
      document.querySelector("#review-state").className = "badge success";
    }
    document.querySelector("#review-name").textContent = item.proveedor || item.archivo_nombre;
    document.querySelector("#review-meta").textContent = `${item.restaurante} · ${item.sucursal} · ${new Date(item.recibida_en).toLocaleString("es-MX")}`;
    if (item.folio) document.querySelector("#review-meta").textContent += ` · N.º ${item.folio}`;
    document.querySelector("#review-state").textContent = item.estado.replaceAll("_", " ");
    document.querySelector("#review-meta").textContent += ` · ${documentType(item.tipo_documento)}`;
    const fileUrl = `/api/v1/facturas/${id}/archivo`;
    document.querySelector("#open-document").href = fileUrl;
    document.querySelector("#document-preview").innerHTML = item.archivo_mime === "application/pdf" || ["application/xml", "text/xml"].includes(item.archivo_mime)
      ? `<iframe title="Factura" src="${fileUrl}"></iframe>`
      : `<img alt="Factura ${escapeHtml(item.archivo_nombre)}" src="${fileUrl}">`;
    renderBranchSuggestion(item.sucursal_deteccion);
    renderFields(item);
    if (!editingApproved) applyFieldConfidence(item.salida_json?.confianza_campos);
    renderValidations(currentCase.validaciones);
    renderRelatedPages(currentCase.paginas_relacionadas || [], id);
    const aliasSource = item.salida_json?.proveedor_ocr_original || item.proveedor_propuesto;
    const aliasRow = document.querySelector("#remember-alias-row");
    if (aliasSource) {
      document.querySelector("#remember-alias-label").textContent = `Recordar “${aliasSource}” como alias del proveedor elegido`;
    } else {
      aliasRow.classList.add("hidden");
    }
    document.querySelector("#remember-alias").onchange = trackChanges;
    document.querySelector("#remember-classification").onchange = trackChanges;
    document.querySelector("#invoice-remember-period").onchange = trackChanges;
    document.querySelector("#approve-button").onclick = () => submitDecision(id);
    document.querySelector("#reject-button").onclick = () => rejectInvoice(id);
    if (editingApproved) {
      const expensePanel = document.querySelector("#approved-expense-panel");
      const expenseFlag = document.querySelector("#approved-generates-expense");
      expensePanel.classList.remove("hidden");
      expenseFlag.checked = item.genera_gasto !== false;
      expenseFlag.dataset.initial = String(expenseFlag.checked);
      expenseFlag.onchange = trackChanges;
      document.querySelector("#reject-button").classList.add("hidden");
      document.querySelector("#approve-button").textContent = "Sin cambios";
      document.querySelector("#approve-button").disabled = true;
      trackChanges();
    } else if (item.tipo_documento && !isExpenseDocumentType(item.tipo_documento)) {
      const overridePanel = document.querySelector("#expense-override-panel");
      const override = document.querySelector("#expense-override");
      const approve = document.querySelector("#approve-button");
      overridePanel.classList.remove("hidden");
      approve.disabled = true;
      approve.textContent = "Marque si genera gasto";
      override.onchange = trackChanges;
      document.querySelector("#reject-button").textContent = "Archivar documento";
    } else if (item.tipo_documento && item.tipo_documento !== "factura_fiscal") {
      document.querySelector("#approve-button").textContent = "Aprobar gasto";
      document.querySelector("#reject-button").textContent = "Rechazar gasto";
    }
  } catch (error) {
    app.innerHTML = `<section class="page"><a href="#/bandeja" class="back-link">← Bandeja</a><div class="empty">${escapeHtml(error.message)}</div></section>`;
  }
}

function renderBranchSuggestion(detection) {
  const panel = document.querySelector("#branch-suggestion");
  if (!detection) return;
  panel.classList.remove("hidden");
  if (detection.metodo === "receptor") {
    const evidence = (detection.coincidencias || []).map(item => escapeHtml(item.valor)).join(" · ");
    panel.classList.add("recognized");
    panel.innerHTML = `<div><span class="suggestion-kicker">SUCURSAL RECONOCIDA</span><strong>${escapeHtml(detection.restaurante || detection.nombre || "Sucursal")}</strong><small>Identificada por RFC, razón social o alias del receptor.${evidence ? ` · ${evidence}` : ""}</small></div>`;
    return;
  }
  const confidence = Math.round(Number(detection.confianza || 0) * 100);
  const products = (detection.productos || []).map(item => `<span>${escapeHtml(item.nombre)}</span>`).join("");
  const scores = (detection.puntajes || []).map(item => `<li><strong>${escapeHtml(item.restaurante)}</strong><span>${Number(item.puntaje || 0)} pts</span></li>`).join("");
  const hasSuggestion = Boolean(detection.clave);
  const title = hasSuggestion ? detection.restaurante : "Sin conclusión suficiente";
  const action = detection.aplicada
    ? "Se preseleccionó esta sucursal; el capturista debe confirmarla o cambiarla."
    : detection.nivel === "alta"
      ? "La factura ya tenía una sucursal seleccionada; no se reemplazó automáticamente."
      : "La evidencia no basta para cambiar la sucursal automáticamente.";
  panel.classList.add(`confidence-${escapeHtml(detection.nivel || "baja")}`);
  panel.innerHTML = `<div class="suggestion-head"><div><span class="suggestion-kicker">INFERENCIA POR CONSUMO · CONFIANZA ${(detection.nivel || "baja").toUpperCase()}</span><strong>${escapeHtml(title)} · ${confidence}%</strong><small>${escapeHtml(action)}</small></div><ul>${scores}</ul></div>${products ? `<div class="product-chips">${products}</div>` : ""}`;
}

function options(items, selected) {
  return items.map(item => `<option value="${item.id}" ${item.id === selected ? "selected" : ""}>${escapeHtml(item.nombre)}</option>`).join("");
}

function optionalOptions(items, selected) {
  return `<option value="">Sin subcategoría</option>${options(items, selected)}`;
}

function branchOptions(selected) {
  return (catalogs?.sucursales || []).map(item => {
    const detail = item.razon_social || item.nombre;
    return `<option value="${item.id}" ${item.id === selected ? "selected" : ""}>${escapeHtml(item.restaurante)} · ${escapeHtml(detail)}${item.rfc ? ` · ${escapeHtml(item.rfc)}` : ""}</option>`;
  }).join("");
}

function renderFields(item) {
  const fields = document.querySelector("#review-fields");
  fields.innerHTML = `
    <label class="wide">Proveedor<input name="proveedor_nombre" list="provider-options" value="${escapeHtml(item.proveedor || "")}" placeholder="Escriba o seleccione el proveedor"><datalist id="provider-options">${catalogs.proveedores.map(provider => `<option value="${escapeHtml(provider.nombre)}"></option>`).join("")}</datalist><input type="hidden" name="proveedor_id" value="${escapeHtml(item.proveedor_id || "")}"></label>
    <label class="reference-field">Número de referencia<input name="folio" value="${escapeHtml(item.folio || "")}" placeholder="Factura, nota, ticket o DDMMYYYY"><small>Referencia principal para buscar el archivo</small></label>
    <label class="branch-field">Sucursal / razón social<select name="sucursal_id">${branchOptions(item.sucursal_id)}</select><small>Puede corregirse en cualquier momento</small></label>
    <label>Fecha de emisión<input type="date" name="fecha_emision" value="${escapeHtml(item.fecha_emision || "")}"></label>
    <label>RFC<input name="rfc_emisor" value="${escapeHtml(item.rfc_emisor || "")}" placeholder="Opcional"></label>
    <label>Subtotal (opcional)<input type="number" step="0.01" name="subtotal" value="${item.subtotal ?? ""}"></label>
    <label>Descuento (opcional)<input type="number" step="0.01" name="descuento" value="${item.descuento ?? ""}"></label>
    <label>IVA (opcional)<input type="number" step="0.01" name="iva" value="${item.iva ?? ""}"></label>
    <label>Otros impuestos (opcional)<input type="number" step="0.01" name="otros_impuestos" value="${item.otros_impuestos ?? ""}"></label>
    <label class="wide">Total<input type="number" step="0.01" name="total" value="${item.total ?? ""}"></label>
    <label>Categoría contable<select name="categoria_id">${options(catalogs.categorias, item.categoria_id)}</select></label>
    <label>Subcategoría (opcional)<select name="subcategoria_id">${optionalOptions(catalogs.subcategorias.filter(x => x.categoria_id === item.categoria_id), item.subcategoria_id)}</select></label>`;
  const form = document.querySelector("#review-form");
  form.elements.observaciones.value = item.observaciones || "";
  initialValues = Object.fromEntries(new FormData(form));
  form.oninput = trackChanges;
  const updateInvoicePeriodification = () => {
    showPeriodification("invoice", {
      visible: catalogCategoryKey(form.elements.categoria_id.value) === "FIJOS",
      referenceDate: form.elements.fecha_emision.value,
      total: form.elements.total.value,
      providerId: form.elements.proveedor_id.value || item.proveedor_id,
      subcategoryId: form.elements.subcategoria_id.value || null,
      existing: item.periodificacion,
    });
  };
  form.elements.categoria_id.onchange = event => {
    const sub = form.elements.subcategoria_id;
    sub.innerHTML = optionalOptions(catalogs.subcategorias.filter(x => x.categoria_id === event.target.value), "");
    updateInvoicePeriodification();
    trackChanges();
  };
  form.elements.subcategoria_id.onchange = updateInvoicePeriodification;
  form.elements.fecha_emision.onchange = updateInvoicePeriodification;
  form.elements.total.oninput = () => {
    updateInvoicePeriodification();
    trackChanges();
  };
  updateInvoicePeriodification();
}

function changes() {
  const current = Object.fromEntries(new FormData(document.querySelector("#review-form")));
  return Object.entries(current).filter(([key, value]) => String(value) !== String(initialValues[key] ?? ""));
}

function trackChanges() {
  const changed = new Set(changes().map(([key]) => key));
  const editingApproved = currentCase?.factura?.estado === "aprobada";
  const periodChanged = editingApproved && invoicePeriodificationChanged();
  const expenseFlag = document.querySelector("#approved-generates-expense");
  const expenseChanged = editingApproved && expenseFlag
    ? String(expenseFlag.checked) !== expenseFlag.dataset.initial
    : false;
  const nonExpense = !isExpenseDocumentType(currentCase?.factura?.tipo_documento);
  const forceAsExpense = nonExpense && document.querySelector("#expense-override")?.checked;
  const approve = document.querySelector("#approve-button");
  const learning = Number(Boolean(document.querySelector("#remember-alias")?.checked))
    + Number(Boolean(document.querySelector("#remember-classification")?.checked))
    + Number(Boolean(document.querySelector("#invoice-remember-period")?.checked));
  document.querySelectorAll("#review-form [name]").forEach(input => input.closest("label").classList.toggle("changed", changed.has(input.name)));
  document.querySelector("#change-count").textContent = forceAsExpense
    ? `Corrección documental${changed.size ? ` · ${changed.size} cambio${changed.size === 1 ? "" : "s"}` : ""}`
    : changed.size ? `${changed.size} cambio${changed.size === 1 ? "" : "s"}${periodChanged ? " · periodo modificado" : ""}${expenseChanged ? " · impacto financiero modificado" : ""}${learning ? ` · ${learning} aprendizaje${learning === 1 ? "" : "s"}` : ""}`
      : periodChanged ? "Periodo modificado"
      : expenseChanged ? "Impacto financiero modificado"
      : learning ? `${learning} aprendizaje${learning === 1 ? "" : "s"}` : "Sin cambios";
  if (editingApproved) {
    const hasChanges = changed.size > 0 || periodChanged || expenseChanged || learning > 0;
    approve.disabled = !hasChanges;
    approve.textContent = hasChanges ? "Guardar cambios" : "Sin cambios";
    return;
  }
  approve.disabled = nonExpense && !forceAsExpense;
  approve.textContent = forceAsExpense
    ? (changed.size ? "Guardar y registrar gasto" : "Registrar como gasto")
    : nonExpense ? "Marque si genera gasto"
    : changed.size ? "Guardar y aprobar" : currentCase?.factura?.tipo_documento === "factura_fiscal" ? "Aprobar factura" : "Aprobar gasto";
}

const CONFIDENCE_FIELDS = {
  proveedor_propuesto: ["proveedor_nombre", "Proveedor"], rfc_emisor: ["rfc_emisor", "RFC"], folio: ["folio", "Folio"],
  fecha_emision: ["fecha_emision", "Fecha"], subtotal: ["subtotal", "Subtotal"], iva: ["iva", "IVA"], total: ["total", "Total"],
};

// Resalta los campos que la lectura automática no pudo confirmar: la revisión empieza por ellos.
function applyFieldConfidence(confidence) {
  const summary = document.querySelector("#uncertain-summary");
  const form = document.querySelector("#review-form");
  if (!summary || !form || !confidence) return;
  const low = [];
  const medium = [];
  Object.entries(CONFIDENCE_FIELDS).forEach(([key, [fieldName, label]]) => {
    const info = confidence[key];
    const input = form.elements[fieldName];
    if (!info || !input || info.nivel === "alta") return;
    const wrapper = input.closest("label");
    if (!wrapper) return;
    wrapper.classList.add(`field-${info.nivel}`);
    wrapper.title = info.motivo;
    const note = document.createElement("small");
    note.className = "field-reason";
    note.textContent = info.motivo;
    wrapper.appendChild(note);
    (info.nivel === "baja" ? low : medium).push(label);
    input.addEventListener("input", () => {
      wrapper.classList.remove("field-baja", "field-media");
      note.remove();
    }, {once: true});
  });
  if (!low.length && !medium.length) return;
  summary.classList.remove("hidden");
  summary.innerHTML = `<strong>Revise primero:</strong> ${low.length ? `<span class="low">${low.join(", ")}</span>` : "ningún campo crítico"}` +
    (medium.length ? ` · <span class="mid">con menos certeza: ${medium.join(", ")}</span>` : "") +
    `<small>Los campos sin marca coincidieron con una segunda fuente (QR del SAT, importe con letra o aritmética).</small>`;
}

function renderRelatedPages(items, invoiceId) {
  const container = document.querySelector("#related-pages");
  const active = items.filter(item => item.estado === "activa");
  if (!container || !active.length) return;
  container.classList.remove("hidden");
  container.innerHTML = `<strong>Páginas del mismo documento</strong>` + active.map(item => `
    <div class="related-page">
      <span>${item.rol === "continuacion" ? "Continuación" : "Documento principal"} · ${escapeHtml(item.archivo_nombre)} · folio ${escapeHtml(item.folio)}</span>
      <span><a class="button ghost small" target="_blank" href="/api/v1/facturas/${item.id}/archivo">Ver página</a>
      ${item.rol === "continuacion" ? `<button class="button ghost small" data-separate="${item.vinculo_id}" type="button">Separar</button>` : `<a class="button ghost small" href="#/facturas/${item.id}">Ir al principal</a>`}</span>
    </div>`).join("");
  container.querySelectorAll("[data-separate]").forEach(button => button.onclick = async () => {
    if (!window.confirm("La página volverá a la bandeja como un documento independiente. ¿Separarla?")) return;
    try {
      await api(`/api/v1/continuaciones/${button.dataset.separate}/separar`, {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({separado_por: operator()}),
      });
      notify("Página separada; vuelve a la bandeja");
      renderReview(invoiceId);
    } catch (error) {
      notify(error.message, true);
    }
  });
}

function renderValidations(items) {
  const errors = items.filter(item => !item.aprobada && item.severidad === "error");
  const summary = document.querySelector("#validation-summary");
  summary.className = `validation-summary ${errors.length ? "bad" : "good"}`;
  summary.textContent = errors.length ? `${errors.length} error${errors.length === 1 ? " requiere" : "es requieren"} atención` : "Validaciones automáticas sin errores";
  const classification = currentCase?.factura;
  if (classification?.tipo_documento) {
    const confidence = Math.round(Number(classification.confianza_clasificacion || 0) * 100);
    summary.textContent = `${documentType(classification.tipo_documento)} · ${confidence}% confianza · ${summary.textContent}`;
  }
  document.querySelector("#validation-list").innerHTML = items.map(item => `
    <div class="validation-item"><strong>${item.aprobada ? "✓" : item.severidad === "error" ? "!" : "i"}</strong><span>${escapeHtml(item.mensaje)}</span></div>`).join("");
}

async function submitDecision(id) {
  const button = document.querySelector("#approve-button");
  button.disabled = true;
  try {
    const changed = changes();
    const editingApproved = currentCase?.factura?.estado === "aprobada";
    const forceAsExpense = !isExpenseDocumentType(currentCase?.factura?.tipo_documento)
      && document.querySelector("#expense-override")?.checked;
    const payload = {
      revisada_por: operator(),
      comentario: null,
      forzar_como_gasto: Boolean(forceAsExpense),
      recordar_alias: Boolean(document.querySelector("#remember-alias")?.checked),
      recordar_clasificacion: Boolean(document.querySelector("#remember-classification")?.checked),
    };
    if (editingApproved) payload.genera_gasto = Boolean(document.querySelector("#approved-generates-expense")?.checked);
    const periodification = periodificationPayload("invoice");
    if (periodification) {
      payload.periodificacion = periodification;
      payload.recordar_periodificacion = Boolean(document.querySelector("#invoice-remember-period")?.checked);
    }
    let endpoint = editingApproved ? "editar" : "aprobar";
    if (editingApproved) {
      payload.correcciones = changed.map(([campo, valor]) => ({campo, valor: valor || null, motivo: "Edición posterior desde interfaz"}));
    } else if (changed.length) {
      endpoint = "corregir";
      payload.correcciones = changed.map(([campo, valor]) => ({campo, valor: valor || null, motivo: "Corrección desde interfaz"}));
    }
    await api(`/api/v1/facturas/${id}/${endpoint}`, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(payload) });
    notify(editingApproved ? "Cambios guardados; Analytics fue actualizado" : forceAsExpense ? "Clasificación corregida y gasto registrado" : changed.length ? "Cambios guardados y gasto aprobado" : "Gasto aprobado");
    if (editingApproved) location.hash = "#/analytics";
    else await continueReviewFlow();
  } catch (error) {
    notify(error.message, true);
    button.disabled = false;
  }
}

async function rejectInvoice(id) {
  const nonExpense = !isExpenseDocumentType(currentCase?.factura?.tipo_documento);
  const reason = window.prompt(
    nonExpense ? "Motivo para archivar el documento:" : "Motivo del rechazo (obligatorio):",
    nonExpense ? `Clasificado como ${documentType(currentCase.factura.tipo_documento)}; no genera gasto` : ""
  );
  if (!reason) return;
  try {
    await api(`/api/v1/facturas/${id}/rechazar`, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({revisada_por: operator(), comentario: reason}) });
    notify(nonExpense ? "Documento archivado fuera del flujo contable" : "Gasto rechazado");
    await continueReviewFlow();
  } catch (error) { notify(error.message, true); }
}

window.addEventListener("hashchange", route);
bootstrap();
