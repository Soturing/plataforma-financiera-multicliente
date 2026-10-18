// Sesión, elección de rol y pantalla "Usuarios y accesos" (fases 3 y 4).
// El servidor decide todo permiso; aquí sólo se muestra lo que ya autorizó.

let session = { autenticado: false, modo: "abierto" };

const MODULE_BY_ROUTE = {
  dashboard: ["DOCUMENTOS"],
  archive: ["DOCUMENTOS"],
  receipts: ["COMPROBANTES"],
  finance: ["FINANZAS"],
  reports: ["REPORTES"],
  analytics: ["FINANZAS"],
  catalogs: ["PROVEEDORES", "CATALOGOS"],
  access: ["IDENTIDADES", "AUDITORIA"],
};

const ROLE_NAMES = {
  CONSULTORA_DIRECTOR: "Director",
  CONSULTORA_SEGURIDAD: "Administrador de seguridad",
  CONSULTORA_CAPTURISTA: "Capturista",
  SOPORTE_TECNICO: "Soporte técnico",
  CLIENTE_RESPONSABLE: "Responsable del cliente",
  CLIENTE_FINANZAS: "Finanzas del cliente",
  CLIENTE_OPERADOR: "Operador de sucursal",
};

const ACCESS_MESSAGES = {
  registrado: "Tu autenticador quedó registrado. Ya puedes iniciar sesión.",
  cancelado: "Inicio de sesión cancelado o vencido. Intenta de nuevo.",
  sin_acceso: "Tu cuenta no tiene acceso activo. Pide ayuda al administrador.",
  sin_asignacion: "Tu cuenta no tiene asignaciones vigentes en este cliente.",
  sesion_distinta: "La confirmación se hizo con otra cuenta; no se aplicó.",
  cerrado: "Sesión cerrada.",
};

async function loadSession() {
  try {
    const response = await fetch("/api/v1/seguridad/sesion", { credentials: "same-origin" });
    session = response.ok ? await response.json() : { autenticado: false, modo: "abierto" };
  } catch {
    session = { autenticado: false, modo: "abierto" };
  }
  renderSessionArea();
  filterNavigation();
  if (session.autenticado && session.requiere_contexto) openContextModal();
  return session;
}

function hasModule(...modules) {
  return session.autenticado && modules.some(m => (session.modulos || []).includes(m));
}

function loginUrl() {
  const destino = "/" + (location.hash || "#/");
  return `/auth/entrar?destino=${encodeURIComponent(destino)}`;
}

function renderSessionArea() {
  const area = document.querySelector("#session-area");
  const operatorField = document.querySelector("#operator-field");
  if (!area) return;
  if (!session.autenticado) {
    operatorField?.classList.toggle("hidden", session.modo === "seguro");
    const modo = session.modo === "seguro" ? "" : `<span class="session-mode" title="El acceso todavía no se exige. Al iniciar sesión se aplican tus permisos.">Modo abierto</span>`;
    area.innerHTML = `${modo}<a class="button small session-login" href="${loginUrl()}">Iniciar sesión</a>`;
    return;
  }
  operatorField?.classList.add("hidden");
  const rol = session.rol ? (ROLE_NAMES[session.rol] || session.rol_nombre || session.rol) : "Sin rol elegido";
  const llave = session.llave_fisica ? `<span class="session-key" title="Sesión iniciada con llave física">🔑</span>` : "";
  area.innerHTML = `
    <div class="session-chip" title="${escapeHtml(session.correo)}">
      <span class="session-avatar" aria-hidden="true">${escapeHtml(initials(session.nombre))}</span>
      <span class="session-text"><strong>${escapeHtml(session.nombre)}</strong><small>${llave}${escapeHtml(rol)} · ${escapeHtml(session.tenant || "")}</small></span>
    </div>
    ${(session.opciones || []).length > 1 ? `<button class="button small ghost-dark" id="switch-role" type="button">Cambiar rol</button>` : ""}
    <button class="button small ghost-dark" id="logout" type="button">Salir</button>`;
  area.querySelector("#switch-role")?.addEventListener("click", openContextModal);
  area.querySelector("#logout").addEventListener("click", logout);
}

function initials(nombre) {
  return String(nombre || "?").split(/\s+/).filter(Boolean).slice(0, 2).map(p => p[0].toUpperCase()).join("");
}

function filterNavigation() {
  document.querySelectorAll(".side-nav a[data-route]").forEach(link => {
    const modules = MODULE_BY_ROUTE[link.dataset.route];
    const visible = !session.autenticado || !modules || session.requiere_contexto || hasModule(...modules);
    link.classList.toggle("hidden", !visible);
  });
}

async function logout() {
  try {
    const response = await fetch("/auth/salir", { method: "POST", credentials: "same-origin" });
    const body = await response.json();
    location.href = body.redirect || "/#/";
  } catch {
    location.href = "/#/";
  }
}

function openContextModal() {
  const modal = document.querySelector("#context-modal");
  const list = document.querySelector("#context-options");
  const options = session.opciones || [];
  list.innerHTML = options.length ? options.map(o => `
    <button class="context-option" type="button" data-id="${o.asignacion_id}" ${o.disponible ? "" : "disabled"}>
      <strong>${escapeHtml(ROLE_NAMES[o.rol] || o.rol_nombre)}</strong>
      <span>${escapeHtml(o.tenant)}${o.sucursales ? ` · Sucursales: ${escapeHtml(o.sucursales.join(", "))}` : " · Todas las sucursales"}</span>
      ${o.disponible ? "" : `<small>${escapeHtml(o.motivo || "No disponible")}</small>`}
      ${session.rol === o.rol ? `<em>Rol actual</em>` : ""}
    </button>`).join("") : `<p class="empty">No tienes asignaciones vigentes en este cliente.</p>`;
  list.querySelectorAll(".context-option:not([disabled])").forEach(button => {
    button.onclick = () => chooseContext(button.dataset.id);
  });
  modal.classList.remove("hidden");
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelector("#close-context")?.addEventListener("click", () => {
    document.querySelector("#context-modal").classList.add("hidden");
  });
  const query = new URLSearchParams((location.hash.split("?")[1]) || "");
  const message = ACCESS_MESSAGES[query.get("acceso")];
  if (message) setTimeout(() => notify(message, ["cancelado", "sin_acceso", "sin_asignacion", "sesion_distinta"].includes(query.get("acceso"))), 400);
});

async function chooseContext(asignacionId) {
  const response = await fetch("/api/v1/seguridad/contexto", {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ asignacion_id: asignacionId }),
  });
  const body = await response.json();
  if (response.status === 401 && body.detail?.url) {
    if (confirm("Para cambiar de rol debes confirmar tu identidad con tu llave o passkey. ¿Continuar?")) location.href = body.detail.url;
    return;
  }
  if (!response.ok) {
    notify(body.detail?.mensaje || body.detail || "No se pudo elegir el rol", true);
    return;
  }
  document.querySelector("#context-modal").classList.add("hidden");
  await loadSession();
  notify(`Trabajando como ${ROLE_NAMES[session.rol] || session.rol}`);
  route();
}

// Llamado por api() cuando el servidor rechaza una operación.
function handleAccessError(status, detail) {
  if (!detail || typeof detail !== "object") return;
  if (detail.codigo === "SESION_REQUERIDA") {
    notify("Inicia sesión para continuar.", true);
    loadSession();
  } else if (detail.codigo === "CONTEXTO_REQUERIDO") {
    loadSession().then(openContextModal);
  } else if (detail.codigo === "REAUTENTICACION_REQUERIDA") {
    if (confirm(`${detail.mensaje}\n\nSe abrirá la confirmación con tu llave o passkey.`)) {
      location.href = `/auth/reautenticar?destino=${encodeURIComponent("/" + (location.hash || "#/"))}`;
    }
  }
}

// --------------------------------------------------------------------------
// Pantalla "Usuarios y accesos"

async function renderAccess() {
  if (!session.autenticado) {
    app.innerHTML = `
      <section class="panel access-panel">
        <div class="panel-title"><div><h2>Usuarios y accesos</h2><p>Personas, roles, sucursales y bitácora de seguridad.</p></div></div>
        <div class="access-empty">
          <p>Esta sección exige iniciar sesión con tu llave física o passkey. No hay contraseñas.</p>
          <a class="button primary" href="${loginUrl()}">Iniciar sesión</a>
        </div>
      </section>`;
    return;
  }
  const canManage = hasModule("IDENTIDADES");
  const canAudit = hasModule("AUDITORIA");
  app.innerHTML = `
    <div class="access-page">
      ${canManage ? `<section class="panel access-panel" id="people-panel">
        <div class="panel-title"><div><h2>Personas con acceso</h2><p id="people-caption">Cargando…</p></div>
          <button class="button primary small" id="open-invite" type="button">＋ Invitar persona</button></div>
        <div id="invite-form-wrap" class="hidden"></div>
        <div class="analytics-table-wrap"><table class="analytics-table access-table">
          <thead><tr><th>Persona</th><th>Estado</th><th>Roles y alcance</th><th>Sesiones</th><th>Último acceso</th><th></th></tr></thead>
          <tbody id="people-rows"></tbody></table></div>
      </section>` : ""}
      <section class="panel access-panel">
        <div class="panel-title"><div><h2>${canAudit ? "Bitácora de seguridad" : "Mi actividad"}</h2><p id="audit-caption">Cargando…</p></div>
          <span id="audit-integrity"></span></div>
        <div class="analytics-table-wrap"><table class="analytics-table access-table">
          <thead><tr><th>Fecha</th><th>Evento</th><th>Resultado</th><th>Persona</th><th>Rol</th><th>Módulo / acción</th><th>Detalle</th></tr></thead>
          <tbody id="audit-rows"></tbody></table></div>
      </section>
    </div>`;
  if (canManage) await loadPeople();
  await loadAudit(canAudit);
}

async function loadPeople() {
  try {
    const data = await api("/api/v1/seguridad/identidades");
    const people = data.identidades || [];
    document.querySelector("#people-caption").textContent = `${people.length} persona${people.length === 1 ? "" : "s"} registradas · alta sólo por invitación de un solo uso (24 h)`;
    document.querySelector("#people-rows").innerHTML = people.map(p => `
      <tr>
        <td><strong>${escapeHtml(p.nombre)}</strong><br><small>${escapeHtml(p.correo)}</small></td>
        <td>${stateBadge(p.estado)}</td>
        <td>${(p.asignaciones || []).map(a => `<div class="access-assignment"><strong>${escapeHtml(ROLE_NAMES[a.rol] || a.rol)}</strong>
             <small>${escapeHtml(a.tenant || "Todos los clientes")} · ${a.sucursales ? escapeHtml(a.sucursales.join(", ")) : "todas las sucursales"}${a.modulos ? ` · ${escapeHtml(a.modulos.join(", "))}` : ""}${(a.condicionados || []).length ? ` · ${escapeHtml(a.condicionados.join(", "))}` : ""}</small></div>`).join("") || "<small>Sin asignaciones</small>"}</td>
        <td>${p.sesiones_abiertas}</td>
        <td>${p.ultimo_acceso_en ? new Date(p.ultimo_acceso_en).toLocaleString("es-MX") : "—"}</td>
        <td class="access-actions">${p.correo === session.correo ? "<small>Tu cuenta</small>" : `
          <button class="button small ghost" data-revoke="${p.id}" type="button">Cerrar sesiones</button>
          ${p.estado !== "SUSPENDIDA" ? `<button class="button small danger" data-suspend="${p.id}" type="button">Suspender</button>` : ""}`}</td>
      </tr>`).join("");
    document.querySelectorAll("[data-suspend]").forEach(b => b.onclick = () => personAction(b.dataset.suspend, "suspender", "Motivo de la suspensión (obligatorio):"));
    document.querySelectorAll("[data-revoke]").forEach(b => b.onclick = () => personAction(b.dataset.revoke, "revocar-sesiones", "Motivo para cerrar sus sesiones (obligatorio):"));
    document.querySelector("#open-invite").onclick = () => renderInviteForm(data.sucursales || []);
  } catch (error) {
    document.querySelector("#people-caption").textContent = error.message;
  }
}

function stateBadge(estado) {
  const kind = { ACTIVA: "success", INVITADA: "warning", REGISTRO_PENDIENTE: "warning" }[estado] || "error";
  const label = { ACTIVA: "Activa", INVITADA: "Invitada", REGISTRO_PENDIENTE: "Registro pendiente", SUSPENDIDA: "Suspendida",
    BLOQUEADA_SEGURIDAD: "Bloqueada", BAJA_DEFINITIVA: "Baja" }[estado] || estado;
  return `<span class="badge ${kind}">${label}</span>`;
}

async function personAction(id, action, question) {
  const motivo = prompt(question);
  if (!motivo || motivo.trim().length < 5) { if (motivo !== null) notify("El motivo debe tener al menos 5 caracteres", true); return; }
  try {
    const result = await api(`/api/v1/seguridad/identidades/${id}/${action}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ motivo }),
    });
    notify(`${action === "suspender" ? "Cuenta suspendida" : "Sesiones cerradas"} · ${result.sesiones_revocadas} sesión(es) revocadas`);
    await loadPeople();
    await loadAudit(hasModule("AUDITORIA"));
  } catch (error) { notify(error.message, true); }
}

function renderInviteForm(branches) {
  const wrap = document.querySelector("#invite-form-wrap");
  const globalAllowed = session.rol === "CONSULTORA_DIRECTOR";
  const roles = Object.entries(ROLE_NAMES).filter(([code]) => globalAllowed || !["CONSULTORA_DIRECTOR", "CONSULTORA_SEGURIDAD", "SOPORTE_TECNICO"].includes(code));
  wrap.innerHTML = `
    <form id="invite-form" class="invite-form">
      <div class="form-grid three">
        <label>Nombre completo<input name="nombre" required minlength="3" maxlength="120"></label>
        <label>Correo<input name="correo" type="email" required maxlength="200"></label>
        <label>Rol<select name="rol">${roles.map(([code, name]) => `<option value="${code}" ${code === "CONSULTORA_CAPTURISTA" ? "selected" : ""}>${name}</option>`).join("")}</select></label>
      </div>
      <fieldset class="invite-branches"><legend>Sucursales</legend>
        <label class="check-row"><input type="checkbox" name="todas" checked><span>Todas las sucursales</span></label>
        ${branches.map(b => `<label class="check-row"><input type="checkbox" name="sucursal" value="${escapeHtml(b.clave)}"><span>${escapeHtml(b.nombre)}</span></label>`).join("")}
      </fieldset>
      <label class="check-row"><input type="checkbox" name="csv"><span>Permitir exportación CSV masiva (permiso individual; exige reautenticación en cada descarga)</span></label>
      <label>Motivo de la invitación<input name="motivo" required minlength="5" maxlength="300" placeholder="Ej. Alta de capturista para el cierre semanal"></label>
      <p class="invite-note">La persona recibirá un enlace de un solo uso válido 24 horas para registrar su passkey (o su llave física si el rol es privilegiado). No se envía ninguna contraseña.</p>
      <div class="form-actions"><button class="button ghost" type="button" id="cancel-invite">Cancelar</button><button class="button primary" type="submit">Enviar invitación</button></div>
    </form>`;
  wrap.classList.remove("hidden");
  const form = wrap.querySelector("#invite-form");
  const all = form.querySelector("[name=todas]");
  const singles = [...form.querySelectorAll("[name=sucursal]")];
  all.onchange = () => { if (all.checked) singles.forEach(s => s.checked = false); };
  singles.forEach(s => s.onchange = () => { if (s.checked) all.checked = false; });
  wrap.querySelector("#cancel-invite").onclick = () => wrap.classList.add("hidden");
  form.onsubmit = async event => {
    event.preventDefault();
    const data = new FormData(form);
    const sucursales = singles.filter(s => s.checked).map(s => s.value);
    const payload = {
      nombre: data.get("nombre").trim(), correo: data.get("correo").trim(), rol: data.get("rol"),
      sucursales: all.checked || !sucursales.length ? null : sucursales,
      condicionados: data.get("csv") ? ["EXPORTAR_CSV"] : [], motivo: data.get("motivo").trim(),
    };
    try {
      await api("/api/v1/seguridad/invitaciones", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      notify(`Invitación enviada a ${payload.correo}`);
      wrap.classList.add("hidden");
      await loadPeople();
      await loadAudit(hasModule("AUDITORIA"));
    } catch (error) { notify(error.message, true); }
  };
}

const EVENT_NAMES = {
  INICIO_SESION: "Inicio de sesión", CIERRE_SESION: "Cierre de sesión", REAUTENTICACION: "Confirmación de identidad",
  CAMBIO_CONTEXTO: "Cambio de rol", ACCESO_DENEGADO: "Acceso denegado", OPERACION_AUTORIZADA: "Operación autorizada",
  INVITACION: "Invitación", SUSPENSION: "Suspensión", REVOCACION_SESIONES: "Sesiones cerradas", ACTIVACION: "Activación de cuenta",
  ALTA_CLIENTE: "Alta de cliente", INSTALACION_DIRECTOR: "Instalación del director", SESION_REVOCADA_REUTILIZADA: "Uso de sesión revocada",
};

async function loadAudit(full) {
  try {
    const data = await api(full ? "/api/v1/seguridad/auditoria" : "/api/v1/seguridad/mi-actividad");
    const events = data.eventos || [];
    document.querySelector("#audit-caption").textContent = full
      ? "Registro de sólo anexado: nadie puede modificarlo ni borrarlo. Cada evento encadena la huella del anterior."
      : "Tus accesos y operaciones sensibles recientes.";
    if (data.integridad) {
      document.querySelector("#audit-integrity").innerHTML = data.integridad.integra
        ? `<span class="badge success" title="Cadena de huellas verificada">Cadena íntegra · ${data.integridad.eventos} eventos</span>`
        : `<span class="badge error">Cadena alterada en el evento ${escapeHtml(data.integridad.primer_problema?.id)}</span>`;
    }
    document.querySelector("#audit-rows").innerHTML = events.length ? events.map(e => `
      <tr class="${e.resultado !== "EXITO" ? "access-rejected" : ""}">
        <td>${new Date(e.ocurrido_en).toLocaleString("es-MX")}</td>
        <td>${escapeHtml(EVENT_NAMES[e.tipo] || e.tipo)}</td>
        <td>${e.resultado === "EXITO" ? `<span class="badge success">Éxito</span>` : `<span class="badge error">${escapeHtml(e.resultado === "RECHAZO" ? "Rechazo" : "Error")}</span>`}</td>
        <td>${escapeHtml(e.actor || (e.actor_tipo === "SISTEMA" ? "Sistema" : "Anónimo"))}</td>
        <td>${escapeHtml(ROLE_NAMES[e.rol] || e.rol || "—")}</td>
        <td>${escapeHtml([e.modulo, e.accion].filter(Boolean).join(" · ") || "—")}</td>
        <td><small>${escapeHtml(e.motivo || e.recurso_tipo || "")}</small></td>
      </tr>`).join("") : `<tr><td colspan="7" class="empty">Sin eventos todavía.</td></tr>`;
  } catch (error) {
    document.querySelector("#audit-caption").textContent = error.message;
  }
}
