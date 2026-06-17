"use strict";

// Página independiente "Imágenes web" servida en https://captura.yoohoo.mx/imagenes/
// Llama al backend FastAPI a través del reverse proxy de nginx en /img-api/
// (el backend escucha solo en 127.0.0.1:8080, nunca expuesto al exterior).
//
// Autenticación: el lanzador me.yoohoo.mx abre esta página con el PIN del
// empleado en el hash de la URL (#pin=NNNN), igual que las demás apps. El PIN
// se envía en la cabecera X-Pin en cada llamada y el backend lo valida contra
// hr.employee (mismo esquema que el checador).

const IMG_API = "/img-api";
const $ = (id) => document.getElementById(id);

// --- PIN desde el hash (#pin=NNNN), igual que el resto de apps del lanzador ---
function readPin() {
  const h = new URLSearchParams((location.hash || "").replace(/^#/, ""));
  return (h.get("pin") || "").trim();
}
const PIN = readPin();

// fetch con la cabecera X-Pin siempre presente
function authFetch(path, opts = {}) {
  const headers = Object.assign({}, opts.headers, { "X-Pin": PIN });
  return fetch(IMG_API + path, Object.assign({}, opts, { headers }));
}
const api = (p) => authFetch(p).then(async (r) => {
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.detail || `Error ${r.status}`);
  }
  return r.json();
});

// --- previsualización de fotos ---
function bindPreview(inputId, previewId) {
  $(inputId).addEventListener("change", (e) => {
    const file = e.target.files[0];
    const img = $(previewId);
    if (!file) { img.classList.remove("show"); return; }
    img.src = URL.createObjectURL(file);
    img.classList.add("show");
  });
}
bindPreview("frente", "prev-frente");
bindPreview("trasero", "prev-trasero");

// --- rellenar selects ---
function fill(select, items, { value = "id", label = "name", placeholder } = {}) {
  select.innerHTML = "";
  if (placeholder) select.insertAdjacentHTML("beforeend",
    `<option value="">${placeholder}</option>`);
  for (const it of items) {
    select.insertAdjacentHTML("beforeend",
      `<option value="${it[value]}">${it[label]}</option>`);
  }
}

function showGate(msg) {
  const g = $("gate");
  g.hidden = false;
  g.textContent = "🔒 " + msg;
  $("form").hidden = true;
}

async function init() {
  if (!PIN) {
    showGate("Abre esta pantalla desde el lanzador (me.yoohoo.mx) para identificarte.");
    return;
  }
  try {
    const tipos = await api("/tipos");           // valida el PIN de paso
    const cats = await api("/categories");
    fill($("tipo"), tipos, { value: "id", label: "label", placeholder: "Elige tipo…" });
    fill($("categoria"), cats, { placeholder: "Elige categoría…" });
    $("form").hidden = false;
  } catch (err) {
    if (/401/.test(err.message) || /PIN/i.test(err.message)) {
      showGate("PIN inválido o sesión no reconocida. Vuelve a entrar desde el lanzador.");
    } else {
      showGate("No se pudo cargar el catálogo: " + err.message);
    }
  }
}

// --- cascada Categoría -> Marca -> Referencia ---
$("categoria").addEventListener("change", async (e) => {
  const id = e.target.value;
  $("marca").disabled = true; $("referencia").disabled = true;
  if (!id) return;
  fill($("marca"), await api(`/brands?category_id=${id}`),
    { placeholder: "Elige marca…" });
  $("marca").disabled = false;
});

$("marca").addEventListener("change", async (e) => {
  const brand = e.target.value;
  const cat = $("categoria").value;
  $("referencia").disabled = true;
  if (!brand) return;
  const refs = await api(`/references?category_id=${cat}&brand=${encodeURIComponent(brand)}`);
  fill($("referencia"), refs, { label: "name", placeholder: "Elige referencia…" });
  $("referencia").disabled = false;
});

// --- envío ---
$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const estado = $("estado");
  const btn = $("enviar");
  const refSel = $("referencia");
  const descripcion = refSel.options[refSel.selectedIndex]?.text || "";

  const fd = new FormData();
  fd.append("reference_id", refSel.value);
  fd.append("tipo", $("tipo").value);
  fd.append("descripcion", descripcion);
  fd.append("frente", $("frente").files[0]);
  fd.append("trasero", $("trasero").files[0]);

  btn.disabled = true;
  estado.hidden = false; estado.className = "estado";
  estado.textContent = "Generando imágenes… esto puede tardar un minuto.";
  try {
    const res = await authFetch("/jobs", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Error");
    estado.className = "estado ok";
    estado.textContent = `✅ Listo: ${data.imagenes} imágenes subidas al producto. ` +
      `Etiqueta "Revisión de imágenes" añadida en Odoo.`;
  } catch (err) {
    estado.className = "estado error";
    estado.textContent = "❌ " + err.message;
  } finally {
    btn.disabled = false;
  }
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("service-worker.js").catch(() => {});
}

init();
