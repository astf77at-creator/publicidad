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
    fill($("tipo"), tipos, { value: "id", label: "label", placeholder: "Elige tipo…" });
    $("form").hidden = false;
  } catch (err) {
    if (/401/.test(err.message) || /PIN/i.test(err.message)) {
      showGate("PIN inválido o sesión no reconocida. Vuelve a entrar desde el lanzador.");
    } else {
      showGate("No se pudo cargar el catálogo: " + err.message);
    }
  }
}

// --- verificación por referencia exacta (SKU) ---
// Producto resuelto: solo se permite generar cuando esto está poblado y
// coincide con el texto actual del campo.
let verificado = null;   // { id, name, default_code } | null

function setRefEstado(msg, cls) {
  const e = $("ref-estado");
  e.hidden = false;
  e.textContent = msg;
  e.className = "ref-estado " + (cls || "");
}

function resetVerificacion() {
  verificado = null;
  $("enviar").disabled = true;
}

async function verificarReferencia() {
  const code = $("referencia").value.trim();
  resetVerificacion();
  if (!code) { setRefEstado("Escribe una referencia.", "error"); return; }
  setRefEstado("Verificando…", "");
  try {
    const r = await authFetch(`/reference/lookup?code=${encodeURIComponent(code)}`);
    if (r.status === 404) { setRefEstado("Referencia no encontrada", "error"); return; }
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw new Error(d.detail || `Error ${r.status}`);
    }
    const prod = await r.json();
    verificado = prod;
    setRefEstado("✓ " + (prod.name || prod.default_code), "ok");
    $("enviar").disabled = false;
  } catch (err) {
    setRefEstado("❌ " + err.message, "error");
  }
}

$("verificar").addEventListener("click", verificarReferencia);
$("referencia").addEventListener("blur", () => {
  if ($("referencia").value.trim()) verificarReferencia();
});
// Cualquier edición invalida la verificación previa.
$("referencia").addEventListener("input", () => {
  if (!verificado || $("referencia").value.trim() !== verificado.default_code) {
    resetVerificacion();
    $("ref-estado").hidden = true;
  }
});

// --- autocompletado (opcional): sugiere referencias mientras se escribe ---
let sugTimer = null;
$("referencia").addEventListener("input", () => {
  const code = $("referencia").value.trim();
  clearTimeout(sugTimer);
  if (code.length < 2) return;
  sugTimer = setTimeout(async () => {
    try {
      const items = await api(`/reference/suggest?code=${encodeURIComponent(code)}`);
      const dl = $("ref-sugerencias");
      dl.innerHTML = "";
      for (const it of items) {
        const o = document.createElement("option");
        o.value = it.default_code;
        o.label = it.name || "";
        dl.appendChild(o);
      }
    } catch (e) { /* sugerencias son best-effort */ }
  }, 250);
});

// --- envío ---
$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const estado = $("estado");
  const btn = $("enviar");

  if (!verificado || $("referencia").value.trim() !== verificado.default_code) {
    setRefEstado("Verifica la referencia antes de generar.", "error");
    resetVerificacion();
    return;
  }

  const fd = new FormData();
  fd.append("reference_id", verificado.id);
  fd.append("tipo", $("tipo").value);
  fd.append("descripcion", verificado.name || verificado.default_code);
  fd.append("frente", $("frente").files[0]);
  fd.append("trasero", $("trasero").files[0]);

  const prog = $("progreso"), relleno = $("barra-relleno"), ptxt = $("progreso-txt");
  function setProg(done, total, label) {
    const pct = total ? Math.round((done / total) * 100) : 0;
    relleno.classList.remove("indeterminada");
    relleno.style.width = pct + "%";
    ptxt.textContent = label;
  }

  btn.disabled = true;
  estado.hidden = true;
  prog.hidden = false;
  relleno.classList.remove("indeterminada");
  relleno.style.width = "0%";
  ptxt.textContent = "Preparando…";

  try {
    const res = await authFetch("/jobs", { method: "POST", body: fd });
    if (!res.ok) {
      // Error antes del stream (401/400): cuerpo JSON.
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `Error ${res.status}`);
    }
    // Lectura del stream NDJSON: un evento por pose.
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "", result = null, errMsg = null;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line); } catch (e) { continue; }
        if (ev.stage === "start") setProg(0, ev.total, `Generando imágenes… 0 de ${ev.total}`);
        else if (ev.stage === "pose") setProg(ev.done, ev.total, `Generando pose ${ev.done} de ${ev.total}…`);
        else if (ev.stage === "uploading") { relleno.classList.add("indeterminada"); ptxt.textContent = "Subiendo imágenes a Odoo…"; }
        else if (ev.stage === "done") result = ev;
        else if (ev.stage === "error") errMsg = ev.detail || "Error generando imágenes";
      }
    }
    if (errMsg) throw new Error(errMsg);
    if (!result) throw new Error("La conexión se interrumpió antes de terminar. Revisa en Odoo si las imágenes se subieron.");
    relleno.classList.remove("indeterminada");
    relleno.style.width = "100%";
    prog.hidden = true;
    estado.hidden = false;
    estado.className = "estado ok";
    estado.textContent = `✅ Listo: ${result.imagenes} imágenes subidas al producto. ` +
      `Etiqueta "Revisión de imágenes" añadida en Odoo.`;
  } catch (err) {
    prog.hidden = true;
    estado.hidden = false;
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
