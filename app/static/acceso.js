// Sesión, elección de rol y pantalla "Usuarios y accesos" (fases 3 y 4).
// El servidor decide todo permiso; aquí sólo se muestra lo que ya autorizó.

let session = { autenticado: false, modo: "abierto" };
let accessCatalog = { restaurantes: [], sucursales: [] };

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
  registro_cancelado: "No se registró el autenticador.",
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
  } else if (detail.codigo === "AUTENTICADOR_PENDIENTE") {
    if (confirm(`${detail.mensaje}

Entraste con un código de recuperación. Se abrirá el registro de tu nueva passkey.`)) {
      location.href = `/auth/registrar-autenticador?destino=${encodeURIComponent("/" + (location.hash || "#/"))}`;
    }
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
      <section class="panel access-panel" id="my-account">
        <div class="panel-title"><div><h2>Mi cuenta</h2><p>Tus autenticadores. Ten siempre al menos dos: si pierdes uno, entras con el otro.</p></div>
          <a class="button small ghost" href="/auth/registrar-autenticador?destino=${encodeURIComponent("/#/accesos")}">＋ Agregar autenticador</a></div>
        <div id="my-authenticators" class="access-devices"></div>
      </section>
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
  await loadMyAccount();
  if (canManage) await loadPeople();
  await loadAudit(canAudit);
}

async function loadMyAccount() {
  const box = document.querySelector("#my-authenticators");
  try {
    const data = await api("/api/v1/seguridad/mi-cuenta");
    const pendiente = data.requiere_nuevo_autenticador
      ? `<p class="access-warning">Entraste con un código de recuperación: registra una passkey nueva para seguir operando.</p>` : "";
    box.innerHTML = pendiente + (data.autenticadores_error
      ? `<p class="access-warning">${escapeHtml(data.autenticadores_error)}</p>` : deviceList(data.autenticadores, "mine"));
    box.querySelectorAll("[data-lost]").forEach(b => b.onclick = () => markLost(null, b.dataset.lost));
  } catch (error) { box.innerHTML = `<p class="empty">${escapeHtml(error.message)}</p>`; }
}

function deviceList(items, owner) {
  if (!items.length) return `<p class="empty">Sin autenticadores registrados.</p>`;
  return `<ul class="device-list">${items.map(d => `
    <li><span class="device-icon">${d.tipo === "webauthn" ? "🔑" : d.tipo === "webauthn-passwordless" ? "📱" : "🧾"}</span>
      <span><strong>${escapeHtml(d.tipo_nombre)}</strong><small>${escapeHtml(d.etiqueta || "")}${d.creado ? ` · desde ${new Date(d.creado).toLocaleDateString("es-MX")}` : ""}</small></span>
      ${d.tipo === "recovery-authn-codes" ? "" : `<button class="button small danger" type="button" data-lost="${d.id}" data-owner="${owner}">Marcar perdido</button>`}
    </li>`).join("")}</ul>`;
}

async function markLost(personId, credentialId) {
  const motivo = prompt("¿Qué pasó con este autenticador? (obligatorio; se cerrarán las sesiones abiertas)");
  if (!motivo || motivo.trim().length < 5) { if (motivo !== null) notify("El motivo debe tener al menos 5 caracteres", true); return; }
  const url = personId
    ? `/api/v1/seguridad/identidades/${personId}/autenticadores/${credentialId}/perdido`
    : `/api/v1/seguridad/mi-cuenta/autenticadores/${credentialId}/perdido`;
  try {
    const r = await api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ motivo }) });
    notify(`Autenticador dado de baja · ${r.sesiones_revocadas} sesión(es) cerradas`);
    if (personId) openPerson(personId); else location.reload();
  } catch (error) { notify(error.message, true); }
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
             <small>${escapeHtml(a.tenant || "Todos los clientes")} · ${scopeText(a)}${a.modulos ? ` · ${escapeHtml(a.modulos.join(", "))}` : ""}${(a.condicionados || []).length ? ` · ${escapeHtml(a.condicionados.join(", "))}` : ""}</small></div>`).join("") || "<small>Sin asignaciones</small>"}</td>
        <td>${p.sesiones_abiertas}</td>
        <td>${p.ultimo_acceso_en ? new Date(p.ultimo_acceso_en).toLocaleString("es-MX") : "—"}</td>
        <td class="access-actions"><button class="button small ghost" data-person="${p.id}" type="button">Ver ficha</button></td>
      </tr>`).join("");
    accessCatalog = { restaurantes: data.restaurantes || [], sucursales: data.sucursales || [] };
    document.querySelectorAll("[data-person]").forEach(b => b.onclick = () => openPerson(b.dataset.person));
    document.querySelector("#open-invite").onclick = () => renderInviteForm(data.restaurantes || [], data.sucursales || []);
  } catch (error) {
    document.querySelector("#people-caption").textContent = error.message;
  }
}

function scopeText(a) {
  if (!a.sucursales) return "todas las sucursales";
  const restaurantes = a.restaurantes || [];
  const sueltas = restaurantes.length ? `${restaurantes.length} restaurante(s) completo(s): ${restaurantes.join(", ")} · sucursales: ` : "";
  return escapeHtml(sueltas + a.sucursales.join(", "));
}

function stateBadge(estado) {
  const kind = { ACTIVA: "success", INVITADA: "warning", REGISTRO_PENDIENTE: "warning" }[estado] || "error";
  const label = { ACTIVA: "Activa", INVITADA: "Invitada", REGISTRO_PENDIENTE: "Registro pendiente", SUSPENDIDA: "Suspendida",
    BLOQUEADA_SEGURIDAD: "Bloqueada", BAJA_DEFINITIVA: "Baja" }[estado] || estado;
  return `<span class="badge ${kind}">${label}</span>`;
}

const PERSON_ACTIONS = {
  "suspender": ["Motivo de la suspensión (obligatorio):", r => `Cuenta suspendida · ${r.sesiones_revocadas} sesión(es) cerradas`],
  "revocar-sesiones": ["Motivo para cerrar sus sesiones (obligatorio):", r => `${r.sesiones_revocadas} sesión(es) cerradas`],
  "reactivar": ["Motivo de la reactivación (obligatorio; revisa antes sus asignaciones):", () => "Cuenta reactivada"],
  "baja": ["Baja definitiva: se revocan sesiones, autenticadores y asignaciones. Motivo (obligatorio):", r => `Baja completada en ${r.segundos} s`],
  "reingreso": ["Reingreso: se enviará una invitación nueva; los permisos anteriores NO se restauran. Motivo:", () => "Invitación de reingreso enviada"],
};

async function personAction(id, action) {
  const [question, done] = PERSON_ACTIONS[action];
  const motivo = prompt(question);
  if (!motivo || motivo.trim().length < 5) { if (motivo !== null) notify("El motivo debe tener al menos 5 caracteres", true); return; }
  try {
    const result = await api(`/api/v1/seguridad/identidades/${id}/${action}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ motivo }),
    });
    notify(done(result));
    await loadPeople();
    await loadAudit(hasModule("AUDITORIA"));
    if (!document.querySelector("#person-modal")?.classList.contains("hidden")) openPerson(id);
  } catch (error) { notify(error.message, true); }
}

function renderInviteForm(restaurants, branches) {
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
      <fieldset class="invite-branches"><legend>Alcance</legend>
        <label class="check-row invite-all"><input type="checkbox" name="todas" checked><span>Todos los restaurantes y sucursales</span></label>
        ${restaurants.filter(r => r.activo).map(r => `
          <div class="invite-restaurant">
            <label class="check-row"><input type="checkbox" name="restaurante" value="${escapeHtml(r.clave)}"><strong>${escapeHtml(r.nombre)}</strong><small>restaurante completo</small></label>
            ${branches.filter(b => b.restaurante_clave === r.clave && b.activa).map(b => `<label class="check-row invite-branch"><input type="checkbox" name="sucursal" value="${escapeHtml(b.clave)}"><span>${escapeHtml(b.nombre)}</span></label>`).join("")}
          </div>`).join("")}
      </fieldset>
      <label class="check-row"><input type="checkbox" name="csv"><span>Permitir exportación CSV masiva (permiso individual; exige reautenticación en cada descarga)</span></label>
      <label>Motivo de la invitación<input name="motivo" required minlength="5" maxlength="300" placeholder="Ej. Alta de capturista para el cierre semanal"></label>
      <p class="invite-note">La persona recibirá un enlace de un solo uso válido 24 horas para registrar su passkey (o su llave física si el rol es privilegiado). No se envía ninguna contraseña.</p>
      <div class="form-actions"><button class="button ghost" type="button" id="cancel-invite">Cancelar</button><button class="button primary" type="submit">Enviar invitación</button></div>
    </form>`;
  wrap.classList.remove("hidden");
  const form = wrap.querySelector("#invite-form");
  const all = form.querySelector("[name=todas]");
  const singles = [...form.querySelectorAll("[name=sucursal], [name=restaurante]")];
  all.onchange = () => { if (all.checked) singles.forEach(s => s.checked = false); };
  singles.forEach(s => s.onchange = () => { if (s.checked) all.checked = false; });
  wrap.querySelector("#cancel-invite").onclick = () => wrap.classList.add("hidden");
  form.onsubmit = async event => {
    event.preventDefault();
    const data = new FormData(form);
    const restaurantes = data.getAll("restaurante");
    const sucursales = data.getAll("sucursal");
    const todo = all.checked || (!restaurantes.length && !sucursales.length);
    const payload = {
      nombre: data.get("nombre").trim(), correo: data.get("correo").trim(), rol: data.get("rol"),
      restaurantes: todo ? null : restaurantes,
      sucursales: todo ? null : sucursales,
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

// --------------------------------------------------------------------------
// Ficha de persona (fase 6: asignaciones, autenticadores, recuperación, baja)

function personModal() {
  let modal = document.querySelector("#person-modal");
  if (!modal) {
    modal = document.createElement("section");
    modal.id = "person-modal";
    modal.className = "upload-modal hidden";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.innerHTML = `<div class="upload-dialog panel person-dialog"><div id="person-body"></div></div>`;
    modal.addEventListener("click", event => { if (event.target === modal) modal.classList.add("hidden"); });
    document.body.appendChild(modal);
  }
  return modal;
}

const PERSON_BUTTONS = {
  ACTIVA: ["suspender", "revocar-sesiones", "baja"],
  SUSPENDIDA: ["reactivar", "baja"],
  BLOQUEADA_SEGURIDAD: ["reactivar", "baja"],
  INVITADA: ["baja"],
  REGISTRO_PENDIENTE: ["baja"],
  BAJA_DEFINITIVA: ["reingreso"],
};
const PERSON_BUTTON_LABELS = {
  "suspender": "Suspender", "revocar-sesiones": "Cerrar sesiones", "reactivar": "Reactivar",
  "baja": "Dar de baja", "reingreso": "Reingreso",
};

async function openPerson(id) {
  const modal = personModal();
  const body = modal.querySelector("#person-body");
  body.innerHTML = `<p class="empty">Cargando…</p>`;
  modal.classList.remove("hidden");
  let data;
  try { data = await api(`/api/v1/seguridad/identidades/${id}`); }
  catch (error) { body.innerHTML = `<p class="empty">${escapeHtml(error.message)}</p>`; return; }
  const p = data.identidad;
  const propia = data.es_tu_cuenta;
  const activas = data.asignaciones.filter(a => a.estado === "ACTIVA");
  const historicas = data.asignaciones.filter(a => a.estado !== "ACTIVA");
  const pendiente = data.recuperaciones.find(r => r.estado === "PENDIENTE");
  const botones = (PERSON_BUTTONS[p.estado] || []).map(a =>
    `<button class="button small ${["baja", "suspender"].includes(a) ? "danger" : "ghost"}" data-act="${a}" type="button">${PERSON_BUTTON_LABELS[a]}</button>`
  ).join("");
  const recuperar = p.estado !== "BAJA_DEFINITIVA" && !pendiente
    ? `<button class="button small ghost" data-recover type="button">Recuperación asistida</button>` : "";
  body.innerHTML = `
    <div class="panel-title"><div><h2>${escapeHtml(p.nombre)}</h2><p>${escapeHtml(p.correo)} · ${stateBadge(p.estado)}${p.motivo_estado ? ` · ${escapeHtml(p.motivo_estado)}` : ""}</p></div>
      <button class="icon-button" type="button" id="close-person" aria-label="Cerrar">×</button></div>
    <div class="person-sections">
      ${propia
        ? `<p class="access-warning">Es tu cuenta: otra persona administradora debe modificar tu acceso. Tus autenticadores se gestionan en "Mi cuenta".</p>`
        : `<div class="person-actions">${botones}${recuperar}</div>`}
      ${p.requiere_nuevo_autenticador ? `<p class="access-warning">Entró con un código de recuperación y debe registrar una passkey nueva.</p>` : ""}
      ${pendiente ? recoveryBox(pendiente, propia) : ""}

      <h3>Roles y alcance</h3>
      ${activas.length ? activas.map(a => assignmentRow(a, propia)).join("") : `<p class="empty">Sin roles activos.</p>`}
      <div id="scope-editor"></div>
      ${propia || p.estado === "BAJA_DEFINITIVA" ? "" : `<button class="button small ghost" data-add-role type="button">＋ Agregar rol</button>`}
      ${historicas.length ? `<details class="person-history"><summary>${historicas.length} asignación(es) anteriores</summary>${historicas.map(a =>
        `<p><small>${escapeHtml(ROLE_NAMES[a.rol] || a.rol)} · ${escapeHtml(a.estado)}${a.revocado_en ? ` · ${new Date(a.revocado_en).toLocaleDateString("es-MX")}` : ""}</small></p>`).join("")}</details>` : ""}

      <h3>Autenticadores</h3>
      ${propia ? `<p class="empty">Gestiónalos en "Mi cuenta".</p>` : data.autenticadores_error ? `<p class="access-warning">${escapeHtml(data.autenticadores_error)}</p>` : deviceList(data.autenticadores, "admin")}

      <h3>Sesiones abiertas (${data.sesiones.length})</h3>
      ${data.sesiones.length ? `<ul class="device-list">${data.sesiones.map(x =>
        `<li><span class="device-icon">🖥</span><span><strong>${escapeHtml(ROLE_NAMES[x.rol_activo] || "Sin rol elegido")}</strong>
          <small>${escapeHtml(x.metodo_auth)} · desde ${new Date(x.creada_en).toLocaleString("es-MX")} · último uso ${new Date(x.ultimo_uso).toLocaleTimeString("es-MX")}</small></span></li>`).join("")}</ul>`
        : `<p class="empty">Ninguna.</p>`}
    </div>`;
  body.querySelector("#close-person").onclick = () => modal.classList.add("hidden");
  body.querySelectorAll("[data-act]").forEach(b => b.onclick = () => personAction(p.id, b.dataset.act));
  body.querySelectorAll("[data-lost]").forEach(b => b.onclick = () => markLost(p.id, b.dataset.lost));
  body.querySelectorAll("[data-revoke-asig]").forEach(b => b.onclick = () => revokeAssignment(p.id, b.dataset.revokeAsig));
  body.querySelectorAll("[data-scope]").forEach(b => b.onclick = () => scopeEditor(p.id, data.asignaciones.find(a => a.id === b.dataset.scope)));
  body.querySelector("[data-add-role]")?.addEventListener("click", () => scopeEditor(p.id, null));
  body.querySelector("[data-recover]")?.addEventListener("click", () => requestRecovery(p.id));
  body.querySelectorAll("[data-recovery-run]").forEach(b => b.onclick = () => recoveryAction(p.id, b.dataset.recoveryRun, "ejecutar"));
  body.querySelectorAll("[data-recovery-cancel]").forEach(b => b.onclick = () => recoveryAction(p.id, b.dataset.recoveryCancel, "cancelar"));
}

function assignmentRow(a, propia) {
  const extras = [
    a.modulos ? `módulos: ${a.modulos.join(", ")}` : "",
    (a.condicionados || []).join(", "),
    a.vigente_hasta ? `vence ${new Date(a.vigente_hasta).toLocaleDateString("es-MX")}` : "",
  ].filter(Boolean).map(x => ` · ${escapeHtml(x)}`).join("");
  const acciones = propia ? "" : `<div class="person-row-actions">
      ${a.tenant ? `<button class="button small ghost" data-scope="${a.id}" type="button">Cambiar alcance</button>` : ""}
      <button class="button small danger" data-revoke-asig="${a.id}" type="button">Revocar</button></div>`;
  return `<div class="person-assignment">
      <div><strong>${escapeHtml(ROLE_NAMES[a.rol] || a.rol)}</strong>
        <small>${escapeHtml(a.tenant || "Todos los clientes")} · ${scopeText(a)}${extras}</small></div>
      ${acciones}
    </div>`;
}

function recoveryBox(r, propia) {
  const listo = new Date(r.ejecutable_desde) <= new Date();
  const cuando = listo ? "la espera de 24 h terminó" : `podrá ejecutarse desde ${new Date(r.ejecutable_desde).toLocaleString("es-MX")}`;
  return `<div class="access-warning recovery-box"><strong>Recuperación asistida pendiente</strong>
    <small>Solicitada ${new Date(r.solicitada_en).toLocaleString("es-MX")} · ${cuando}</small>
    ${propia ? "" : `<div class="person-row-actions">
      <button class="button small primary" data-recovery-run="${r.id}" type="button" ${listo ? "" : "disabled"}>Ejecutar</button>
      <button class="button small ghost" data-recovery-cancel="${r.id}" type="button">Cancelar</button></div>`}</div>`;
}

async function requestRecovery(personId) {
  const verificacion = prompt("Recuperación asistida. ¿Cómo verificaste su identidad por un canal registrado previamente? (obligatorio)");
  if (!verificacion || verificacion.trim().length < 5) return;
  const motivo = prompt("Motivo (obligatorio). Se cerrarán sus sesiones y habrá una espera de 24 h antes de ejecutar:");
  if (!motivo || motivo.trim().length < 5) return;
  try {
    const r = await api(`/api/v1/seguridad/identidades/${personId}/recuperacion`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ motivo, verificacion }),
    });
    notify(`Recuperación registrada; podrá ejecutarse desde ${new Date(r.ejecutable_desde).toLocaleString("es-MX")}`);
    openPerson(personId);
  } catch (error) { notify(error.message, true); }
}

async function recoveryAction(personId, recoveryId, action) {
  let body = {};
  if (action === "cancelar") {
    const motivo = prompt("Motivo de la cancelación (obligatorio):");
    if (!motivo || motivo.trim().length < 5) return;
    body = { motivo };
  } else if (!confirm("Se darán de baja TODOS sus autenticadores y recibirá un enlace nuevo para registrar uno. ¿Continuar?")) {
    return;
  }
  try {
    await api(`/api/v1/seguridad/recuperaciones/${recoveryId}/${action}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    notify(action === "ejecutar" ? "Recuperación ejecutada; se envió la invitación nueva" : "Recuperación cancelada");
    openPerson(personId);
  } catch (error) { notify(error.message, true); }
}

async function revokeAssignment(personId, assignmentId) {
  const motivo = prompt("Motivo para revocar este rol (obligatorio; sus sesiones con ese rol se cerrarán):");
  if (!motivo || motivo.trim().length < 5) return;
  try {
    const r = await api(`/api/v1/seguridad/asignaciones/${assignmentId}/revocar`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ motivo }),
    });
    notify(`Rol revocado · ${r.sesiones_revocadas} sesión(es) cerradas`);
    openPerson(personId);
    loadPeople();
  } catch (error) { notify(error.message, true); }
}

function scopeEditor(personId, assignment) {
  const box = document.querySelector("#scope-editor");
  const { restaurantes, sucursales } = accessCatalog;
  const nuevo = !assignment;
  const globalAllowed = session.rol === "CONSULTORA_DIRECTOR";
  const roles = Object.entries(ROLE_NAMES).filter(([code]) =>
    globalAllowed || !["CONSULTORA_DIRECTOR", "CONSULTORA_SEGURIDAD", "SOPORTE_TECNICO"].includes(code));
  const elegidosR = new Set(assignment?.restaurantes || []);
  const elegidosS = new Set(assignment ? (assignment.sucursales || []) : []);
  const bloques = restaurantes.filter(r => r.activo).map(r => {
    const suyas = sucursales.filter(b => b.restaurante_clave === r.clave && b.activa).map(b =>
      `<label class="check-row invite-branch"><input type="checkbox" name="sucursal" value="${escapeHtml(b.clave)}" ${elegidosS.has(b.clave) && !elegidosR.has(r.clave) ? "checked" : ""}><span>${escapeHtml(b.nombre)}</span></label>`
    ).join("");
    return `<div class="invite-restaurant">
      <label class="check-row"><input type="checkbox" name="restaurante" value="${escapeHtml(r.clave)}" ${elegidosR.has(r.clave) ? "checked" : ""}><strong>${escapeHtml(r.nombre)}</strong><small>restaurante completo</small></label>
      ${suyas}</div>`;
  }).join("");
  box.innerHTML = `
    <form class="invite-form" id="scope-form">
      ${nuevo
        ? `<label>Rol<select name="rol">${roles.map(([c, n]) => `<option value="${c}">${n}</option>`).join("")}</select></label>`
        : `<p><strong>${escapeHtml(ROLE_NAMES[assignment.rol] || assignment.rol)}</strong></p>`}
      <fieldset class="invite-branches"><legend>Alcance</legend>
        <label class="check-row invite-all"><input type="checkbox" name="todas" ${!assignment || !assignment.sucursales ? "checked" : ""}><span>Todos los restaurantes y sucursales</span></label>
        ${bloques}
      </fieldset>
      <label class="check-row"><input type="checkbox" name="csv" ${(assignment?.condicionados || []).includes("EXPORTAR_CSV") ? "checked" : ""}><span>Permitir exportación CSV masiva</span></label>
      <label>Vigente hasta (opcional)<input type="date" name="vigente_hasta" value="${assignment?.vigente_hasta ? assignment.vigente_hasta.slice(0, 10) : ""}"></label>
      <label>Motivo (obligatorio)<input name="motivo" required minlength="5" maxlength="300"></label>
      <p class="invite-note">Reducir el acceso cierra de inmediato sus sesiones con este rol. Ampliarlo exige autenticación reciente y avisa a la persona y al director.</p>
      <div class="form-actions"><button class="button ghost" type="button" id="cancel-scope">Cancelar</button>
        <button class="button primary" type="submit">${nuevo ? "Agregar rol" : "Guardar alcance"}</button></div>
    </form>`;
  const form = box.querySelector("#scope-form");
  const all = form.querySelector("[name=todas]");
  const singles = [...form.querySelectorAll("[name=sucursal], [name=restaurante]")];
  all.onchange = () => { if (all.checked) singles.forEach(x => x.checked = false); };
  singles.forEach(x => x.onchange = () => { if (x.checked) all.checked = false; });
  box.querySelector("#cancel-scope").onclick = () => { box.innerHTML = ""; };
  form.onsubmit = async event => {
    event.preventDefault();
    const data = new FormData(form);
    const todo = all.checked || (!data.getAll("restaurante").length && !data.getAll("sucursal").length);
    const payload = {
      restaurantes: todo ? null : data.getAll("restaurante"),
      sucursales: todo ? null : data.getAll("sucursal"),
      condicionados: data.get("csv") ? ["EXPORTAR_CSV"] : [],
      motivo: data.get("motivo").trim(),
      vigente_hasta: data.get("vigente_hasta") ? new Date(data.get("vigente_hasta") + "T23:59:59").toISOString() : null,
      modulos: assignment?.modulos ?? null,
    };
    if (nuevo) payload.rol = data.get("rol");
    const url = nuevo ? `/api/v1/seguridad/identidades/${personId}/asignaciones` : `/api/v1/seguridad/asignaciones/${assignment.id}`;
    try {
      const r = await api(url, { method: nuevo ? "POST" : "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      notify(nuevo ? "Rol agregado" : r.tipo === "REDUCCION" ? "Acceso reducido; sus sesiones se cerraron" : "Acceso ampliado");
      openPerson(personId);
      loadPeople();
    } catch (error) { notify(error.message, true); }
  };
}
