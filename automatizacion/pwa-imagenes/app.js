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
    startColaTimer();   // muestra los trabajos pendientes ya existentes (compartidos)
  } catch (err) {
    if (/401/.test(err.message) || /PIN/i.test(err.message)) {
      showGate("PIN inválido o sesión no reconocida. Vuelve a entrar desde el lanzador.");
    } else {
      showGate("No se pudo cargar el catálogo: " + err.message);
    }
  }
}

// --- verificación por referencia exacta (SKU) ---
// Producto resuelto: solo se permite añadir cuando esto está poblado y
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
  const wrap = $("color-wrap");
  if (wrap) { wrap.hidden = true; $("color").innerHTML = ""; }
}

// Carga los colores (variantes) del producto verificado. Si tiene colores,
// muestra el selector y EXIGE elegir uno antes de añadir; si no tiene, deja
// añadir a nivel plantilla (comportamiento anterior).
async function loadColors(code) {
  const wrap = $("color-wrap"), sel = $("color");
  wrap.hidden = true;
  try {
    const data = await api(`/reference/variants?code=${encodeURIComponent(code)}`);
    const colors = (data && data.colors) || [];
    sel.innerHTML = "";            // limpiar AQUÍ (tras el fetch) evita lista duplicada
    if (!colors.length) { $("enviar").disabled = false; return; }
    sel.insertAdjacentHTML("beforeend", `<option value="">Elige color…</option>`);
    for (const c of colors) {
      const qty = Math.round(c.qty || 0);
      const label = `${c.color} · ${qty} pza${qty === 1 ? "" : "s"}`;
      sel.insertAdjacentHTML("beforeend",
        `<option value="${c.variant_ids.join(",")}">${esc(label)}</option>`);
    }
    wrap.hidden = false;
    $("enviar").disabled = true;   // exige elegir color
  } catch (e) {
    sel.innerHTML = "";
    $("enviar").disabled = false;  // si falla, no bloquea (añade a plantilla)
  }
}

$("color").addEventListener("change", () => {
  $("enviar").disabled = !$("color").value;
});

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
    await loadColors(prod.default_code);   // muestra selector de color si aplica
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

// ======================================================================
//  COLA DE GENERACIÓN
//  El usuario captura un flujo (fotos + tipo + referencia + color) y lo
//  AÑADE a la cola; el formulario se limpia para el siguiente. El backend
//  procesa los trabajos en segundo plano (2 a la vez). Aquí mostramos una
//  tarjeta por trabajo con barra de progreso y consultamos su estado.
// ======================================================================
const MAX_COLA = 20;          // máximo de trabajos activos permitidos al añadir
let ultimoActivos = 0;        // nº de activos según la última consulta
let colaTimer = null;

function estadoTxt(j) {
  if (j.estado === "en_cola") return "En cola…";
  if (j.estado === "listo") return `✅ Listo (${j.imagenes || 0})`;
  if (j.estado === "error") return "❌ " + (j.detail || "Error");
  if (/subiendo/i.test(j.etapa || "")) return "Subiendo a Odoo…";
  return `Generando ${j.done || 0}/${j.total || 0}`;
}
function barraPct(j) {
  if (j.estado === "listo") return 100;
  if (j.estado === "en_cola") return 0;
  const t = j.total || 0, d = j.done || 0;
  return t ? Math.round((d / t) * 100) : 0;
}
function esIndeterminada(j) {
  return j.estado === "en_cola" ||
    (j.estado === "procesando" && /subiendo/i.test(j.etapa || ""));
}

// Consulta al backend la lista COMPLETA de trabajos y pinta el panel. Así se
// ven todos los pendientes (de cualquier operador) y sobrevive a recargas.
async function refreshCola() {
  let jobs;
  try { jobs = await api("/jobs"); } catch (e) { return; }
  const panel = $("cola");
  if (!jobs.length) { panel.hidden = true; ultimoActivos = 0; return; }
  panel.hidden = false;
  ultimoActivos = jobs.filter(
    (j) => j.estado === "en_cola" || j.estado === "procesando").length;
  $("cola-head").textContent =
    `Cola de generación · ${ultimoActivos} pendientes · ${jobs.length} en total`;
  $("cola-lista").innerHTML = jobs.map((j) => {
    const cls = j.estado === "listo" ? " ok" : j.estado === "error" ? " error" : "";
    const rell = "relleno" + (esIndeterminada(j) ? " indeterminada" : "");
    return `<div class="job${cls}"><div class="job-top">` +
      `<span class="job-label">${esc(j.titulo || j.producto || "")}</span>` +
      `<span class="job-estado">${esc(estadoTxt(j))}</span></div>` +
      `<div class="barra"><div class="${rell}" style="width:${barraPct(j)}%"></div></div>` +
      `</div>`;
  }).join("");
}

function startColaTimer() {
  refreshCola();
  if (colaTimer) return;
  colaTimer = setInterval(refreshCola, 2500);
}

function resetForm() {
  $("frente").value = "";
  $("trasero").value = "";
  $("prev-frente").classList.remove("show");
  $("prev-trasero").classList.remove("show");
  $("referencia").value = "";
  $("ref-estado").hidden = true;
  resetVerificacion();   // limpia verificado + color y deshabilita el botón
}

// --- añadir a la cola ---
$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("enviar");

  if (!verificado || $("referencia").value.trim() !== verificado.default_code) {
    setRefEstado("Verifica la referencia antes de añadir.", "error");
    resetVerificacion();
    return;
  }
  const colorWrap = $("color-wrap");
  const tieneColor = colorWrap && !colorWrap.hidden;
  if (tieneColor && !$("color").value) {
    setRefEstado("Elige el color antes de añadir.", "error");
    return;
  }
  if (!$("frente").files[0] || !$("trasero").files[0]) {
    setRefEstado("Faltan las dos fotos (frente y trasero).", "error");
    return;
  }
  if (ultimoActivos >= MAX_COLA) {
    setRefEstado(`La cola está llena (${MAX_COLA} pendientes). Espera a que terminen algunos.`, "error");
    return;
  }

  const colorTxt = tieneColor ? (" · " + (($("color").selectedOptions[0] || {}).text || "")) : "";
  const label = (verificado.default_code || verificado.name) + colorTxt;

  const fd = new FormData();
  fd.append("reference_id", verificado.id);
  fd.append("tipo", $("tipo").value);
  fd.append("descripcion", verificado.name || verificado.default_code);
  fd.append("frente", $("frente").files[0]);
  fd.append("trasero", $("trasero").files[0]);
  fd.append("codigo", verificado.default_code || "");   // se estampa discreto en la imagen
  fd.append("titulo", label);                           // etiqueta para la lista de la cola
  if (tieneColor && $("color").value) fd.append("variant_ids", $("color").value);

  btn.disabled = true;
  try {
    const res = await authFetch("/jobs", { method: "POST", body: fd });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `Error ${res.status}`);
    }
    await res.json();
    startColaTimer();      // refresca la lista de la cola desde el backend
    resetForm();
    const estado = $("estado");
    estado.hidden = false;
    estado.className = "estado ok";
    estado.textContent = "✅ Añadido a la cola. Captura el siguiente.";
  } catch (err) {
    setRefEstado("❌ " + err.message, "error");
    btn.disabled = false;
  }
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("service-worker.js").catch(() => {});
}

init();
