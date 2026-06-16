"use strict";

const $ = (id) => document.getElementById(id);
const api = (p) => fetch(p).then((r) => r.json());

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

async function init() {
  fill($("tipo"), await api("/api/tipos"), { value: "id", label: "label",
    placeholder: "Elige tipo…" });
  fill($("categoria"), await api("/api/categories"),
    { placeholder: "Elige categoría…" });
}

// --- cascada Categoría -> Marca -> Referencia ---
$("categoria").addEventListener("change", async (e) => {
  const id = e.target.value;
  $("marca").disabled = true; $("referencia").disabled = true;
  if (!id) return;
  fill($("marca"), await api(`/api/brands?category_id=${id}`),
    { placeholder: "Elige marca…" });
  $("marca").disabled = false;
});

$("marca").addEventListener("change", async (e) => {
  const brand = e.target.value;
  const cat = $("categoria").value;
  $("referencia").disabled = true;
  if (!brand) return;
  const refs = await api(`/api/references?category_id=${cat}&brand=${encodeURIComponent(brand)}`);
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
    const res = await fetch("/api/jobs", { method: "POST", body: fd });
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
