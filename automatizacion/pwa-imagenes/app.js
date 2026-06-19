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
  $("btn-faltantes").hidden = true;
  $("faltantes").hidden = true;
}

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
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
    $("btn-faltantes").hidden = false;
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

// --- panel "productos sin imagen" (priorizados por stock) ---
async function cargarFaltantes() {
  const panel = $("faltantes");
  panel.hidden = false;
  panel.innerHTML = '<div class="faltantes-msg">Cargando productos sin imagen…</div>';
  try {
    const items = await api("/products/missing-images");
    if (!items.length) {
      panel.innerHTML = '<div class="faltantes-msg">No hay productos con stock sin imagen. 🎉</div>';
      return;
    }
    let html = `<div class="faltantes-head">${items.length} productos sin imagen (con stock) · toca uno para usarlo</div>`;
    let cat = null;
    for (const it of items) {
      if (it.categoria !== cat) {
        cat = it.categoria;
        html += `<div class="faltantes-cat">${esc(cat)}</div>`;
      }
      html += `<div class="faltantes-row" data-code="${esc(it.default_code)}">` +
        `<span class="fq" title="piezas disponibles">${it.qty}</span>` +
        `<span class="fc">${esc(it.default_code)}</span>` +
        `<span class="fn">${esc(it.name)}</span></div>`;
    }
    panel.innerHTML = html;
    panel.querySelectorAll(".faltantes-row").forEach((row) => {
      row.addEventListener("click", () => {
        $("referencia").value = row.getAttribute("data-code");
        panel.hidden = true;
        verificarReferencia();
        $("form").scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  } catch (err) {
    panel.innerHTML = `<div class="faltantes-msg error">❌ ${esc(err.message)}</div>`;
  }
}

$("btn-faltantes").addEventListener("click", () => {
  const panel = $("faltantes");
  if (panel.hidden) cargarFaltantes();   // abrir: recarga fresco (la lista cambia)
  else panel.hidden = true;              // cerrar
});

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
  // Estado de progreso + estimación de tiempo restante (ETA).
  let t0 = 0, label = "Preparando…", eta = null, tick = null;
  const SEG_POR_POSE = 30;   // estimación inicial por pose, hasta medir la 1ª

  function fmtEta(s) {
    if (s == null) return "";
    if (s <= 1) return "casi listo…";
    if (s < 60) return `~${Math.round(s)} s restantes`;
    return `~${Math.ceil(s / 60)} min restantes`;
  }
  function render() {
    ptxt.textContent = eta != null ? `${label} · ${fmtEta(eta)}` : label;
  }
  function setBar(done, total) {
    relleno.classList.remove("indeterminada");
    relleno.style.width = (total ? Math.round((done / total) * 100) : 0) + "%";
  }
  function startTick() {
    clearInterval(tick);
    tick = setInterval(() => {        // cuenta regresiva suave entre poses
      if (eta != null && eta > 1) { eta -= 1; render(); }
    }, 1000);
  }
  function stopTick() { clearInterval(tick); tick = null; }

  btn.disabled = true;
  estado.hidden = true;
  prog.hidden = false;
  relleno.classList.remove("indeterminada");
  relleno.style.width = "0%";
  render();

  try {
    // 1) Encolar el trabajo: el backend responde de inmediato con un job_id.
    const res = await authFetch("/jobs", { method: "POST", body: fd });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `Error ${res.status}`);
    }
    const { job_id } = await res.json();

    // El trabajo se procesa en el SERVIDOR (cola). Aunque cierres la página,
    // sigue su curso. Aquí solo consultamos el estado periódicamente.
    label = "En cola…"; eta = null;
    relleno.classList.add("indeterminada");
    render();

    let result = null;
    for (;;) {
      await new Promise((r) => setTimeout(r, 1500));
      let job;
      try { job = await api(`/jobs/${job_id}`); }
      catch (e) { continue; }   // reintenta ante fallos puntuales de red

      if (job.estado === "en_cola") {
        relleno.classList.add("indeterminada");
        label = "En cola…"; eta = null; render();
      } else if (job.estado === "procesando") {
        if (!t0) t0 = Date.now();
        const total = job.total || 0, done = job.done || 0;
        if (job.etapa && /subiendo/i.test(job.etapa)) {
          relleno.classList.add("indeterminada");
          label = "Subiendo imágenes a Odoo…"; eta = null; render();
        } else {
          setBar(done, total);
          label = `Generando imágenes… ${done} de ${total}`;
          if (done > 0) {
            const porPose = ((Date.now() - t0) / 1000) / done;
            eta = done >= total ? null : Math.round(porPose * (total - done));
          }
          render();
        }
      } else if (job.estado === "listo") {
        result = job; break;
      } else if (job.estado === "error") {
        throw new Error(job.detail || "Error generando imágenes");
      }
    }

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
    stopTick();
    btn.disabled = false;
  }
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("service-worker.js").catch(() => {});
}

init();
