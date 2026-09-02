"use strict";

// Esta vista no persiste identidad, permisos, tokens ni el último cliente elegido.
const previewTenants = [
  {
    id: "synthetic-north",
    name: "Grupo Norteño · ficticio",
    branches: ["Consolidado autorizado", "Centro", "Aeropuerto", "Terraza"],
    pending: [18, 7, 6, 5],
  },
  {
    id: "synthetic-central",
    name: "Mesa Central · ficticio",
    branches: ["Consolidado autorizado", "Reforma", "Del Valle"],
    pending: [11, 8, 3],
  },
  {
    id: "synthetic-coast",
    name: "Cocina del Puerto · ficticio",
    branches: ["Consolidado autorizado", "Malecón", "Marina", "Mercado"],
    pending: [14, 4, 7, 3],
  },
];

const tenantSelect = document.querySelector("#tenant-select");
const branchSelect = document.querySelector("#branch-select");
const activeTenant = document.querySelector("#active-tenant");
const activeBranch = document.querySelector("#active-branch");
const activeBranchKicker = document.querySelector("#active-branch-kicker");
const contextNote = document.querySelector("#context-note-text");
const metricPending = document.querySelector("#metric-pending");
const queueCaption = document.querySelector("#queue-caption");

function selectedTenant() {
  return previewTenants.find((tenant) => tenant.id === tenantSelect.value) || previewTenants[0];
}

function replaceOptions(select, options) {
  const fragment = document.createDocumentFragment();
  options.forEach(({ value, label }) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    fragment.append(option);
  });
  select.replaceChildren(fragment);
}

function renderTenantOptions() {
  replaceOptions(
    tenantSelect,
    previewTenants.map((tenant) => ({ value: tenant.id, label: tenant.name })),
  );
}

function renderBranches() {
  const tenant = selectedTenant();
  replaceOptions(
    branchSelect,
    tenant.branches.map((branch, index) => ({ value: String(index), label: branch })),
  );
  branchSelect.value = "0";
  renderContext();
}

function renderContext() {
  const tenant = selectedTenant();
  const branchIndex = Number(branchSelect.value || 0);
  const branch = tenant.branches[branchIndex];
  const pending = tenant.pending[branchIndex];

  activeTenant.textContent = tenant.name.replace(" · ficticio", "");
  activeBranch.textContent = branch;
  activeBranchKicker.textContent = branch.toUpperCase();
  metricPending.textContent = String(pending);
  queueCaption.textContent = `${pending} documentos en ${branch.toLowerCase()}`;
  contextNote.textContent = branchIndex === 0
    ? "Vista consolidada permitida por tu asignación. Nunca combina clientes."
    : "Toda consulta y cambio llevará este cliente y esta sucursal al servidor.";
}

tenantSelect.addEventListener("change", renderBranches);
branchSelect.addEventListener("change", renderContext);

const profileButton = document.querySelector("#profile-button");
const profileMenu = document.querySelector("#profile-menu");
profileButton.addEventListener("click", () => {
  const willOpen = profileMenu.hidden;
  profileMenu.hidden = !willOpen;
  profileButton.setAttribute("aria-expanded", String(willOpen));
});
document.addEventListener("click", (event) => {
  if (!profileMenu.hidden && !event.target.closest(".session-summary")) {
    profileMenu.hidden = true;
    profileButton.setAttribute("aria-expanded", "false");
  }
});

const sidebar = document.querySelector("#sidebar");
const sidebarScrim = document.querySelector("#sidebar-scrim");
const navToggle = document.querySelector("#nav-toggle");
function setSidebar(open) {
  sidebar.classList.toggle("open", open);
  sidebarScrim.classList.toggle("open", open);
  navToggle.setAttribute("aria-expanded", String(open));
}
navToggle.addEventListener("click", () => setSidebar(!sidebar.classList.contains("open")));
sidebarScrim.addEventListener("click", () => setSidebar(false));

const scopeDialog = document.querySelector("#scope-dialog");
document.querySelector("#scope-details").addEventListener("click", () => scopeDialog.showModal());

renderTenantOptions();
renderBranches();
