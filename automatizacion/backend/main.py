"""API FastAPI que orquesta: PWA -> OpenAI -> Odoo.

Flujo principal (POST /api/jobs):
  1. Recibe 2 fotos (frente + trasero) + referencia elegida + tipo de prenda.
  2. Genera N poses con OpenAI usando las fotos como referencia.
  3. Convierte cada pose a WEBP 800x1000 <=100KB.
  4. Sube las imágenes al producto en Odoo.
  5. Añade etiquetas "Revisión de imágenes" + "Listo".

La generación NO se hace en línea: se ENCOLA. POST /api/jobs responde de
inmediato con un job_id y un worker en segundo plano (concurrencia limitada)
procesa el trabajo. El front consulta el avance con GET /api/jobs/{job_id}.
Así varios usuarios pueden mandar trabajos a la vez sin 504 y el proceso
continúa aunque se cierre la página.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

from .config import settings
from .imaging import to_webp
from .odoo import get_auth_odoo, get_odoo
from .openai_images import generate_pose
from .prompts import REFUERZO_SEGURO, TIPOS, build_prompt, poses_for

app = FastAPI(title="Automatización de imágenes de producto")
log = logging.getLogger("automatizacion")


# ---------- autenticación por PIN ----------
# Mismo esquema que el lanzador me.yoohoo.mx: el PIN del empleado llega en la
# cabecera X-Pin y se valida contra hr.employee. Así /img-api/ no queda abierto.
def require_pin(x_pin: str | None = Header(default=None)) -> dict:
    value = (x_pin or "").strip()
    if not value:
        raise HTTPException(401, "PIN requerido. Entra desde el lanzador.")
    emp = get_auth_odoo().find_employee_by_pin(value)
    if not emp:
        raise HTTPException(401, "PIN inválido.")
    return emp


# ---------- catálogos / cascada ----------
@app.get("/api/tipos")
def tipos(_emp: dict = Depends(require_pin)):
    return [{"id": k, "label": v["label"]} for k, v in TIPOS.items()]


@app.get("/api/categories")
def categories(_emp: dict = Depends(require_pin)):
    return get_odoo().get_categories()


@app.get("/api/brands")
def brands(category_id: int, _emp: dict = Depends(require_pin)):
    return get_odoo().get_brands(category_id)


@app.get("/api/references")
def references(category_id: int, brand: str, _emp: dict = Depends(require_pin)):
    val: str | int = int(brand) if brand.isdigit() else brand
    return get_odoo().get_references(category_id, val)


# ---------- productos sin imagen (priorizados por stock) ----------
@app.get("/api/products/missing-images")
def products_missing_images(_emp: dict = Depends(require_pin)):
    return get_odoo().products_missing_images()


# ---------- verificación por referencia exacta (SKU) ----------
@app.get("/api/reference/lookup")
def reference_lookup(code: str, _emp: dict = Depends(require_pin)):
    """Busca un producto por referencia EXACTA (default_code).

    200 -> {id, name, default_code}.  404 -> referencia no encontrada.
    """
    prod = get_odoo().lookup_reference(code)
    if not prod:
        raise HTTPException(404, "Referencia no encontrada")
    return prod


@app.get("/api/reference/suggest")
def reference_suggest(code: str, _emp: dict = Depends(require_pin)):
    """Autocompletado: referencias que empiezan por `code` (máx. 8)."""
    return get_odoo().suggest_references(code)


@app.get("/api/reference/variants")
def reference_variants(code: str, _emp: dict = Depends(require_pin)):
    """Colores (variantes) del producto de esa referencia.

    {template, colors:[{color, variant_ids:[...]}]}. colors vacío si el producto
    no tiene atributo de color (entonces se genera a nivel plantilla).
    """
    data = get_odoo().get_color_variants(code)
    if not data:
        raise HTTPException(404, "Referencia no encontrada")
    return data


# ========================================================================
#  COLA DE TRABAJOS
#  Un worker pool con concurrencia limitada procesa los trabajos en segundo
#  plano. El estado vive en memoria (suficiente para este caso); si el
#  servicio se reinicia, los trabajos en curso se pierden (hay que reenviar).
# ========================================================================
_executor = ThreadPoolExecutor(max_workers=max(1, settings.concurrencia_jobs))
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _update(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.update(fields)
            job["actualizado"] = time.time()


def _prune(max_age: float = 7200) -> None:
    """Limpia trabajos terminados (listo/error) viejos para no acumular RAM."""
    now = time.time()
    with _jobs_lock:
        viejos = [
            k for k, v in _jobs.items()
            if v["estado"] in ("listo", "error") and now - v["actualizado"] > max_age
        ]
        for k in viejos:
            _jobs.pop(k, None)


def _generar_pose(these_refs, tipo, descripcion, pose, con_ancla):
    """Genera una pose. Si OpenAI la rechaza por MODERACIÓN, reintenta con un
    prompt recatado y pose neutra. Devuelve el PNG, o None si aun así queda
    bloqueada (se omite esa pose sin tumbar el trabajo entero).
    Otros errores (cuota, red, formato) se propagan como siempre.
    """
    prompt = build_prompt(tipo, descripcion, pose, anchor=con_ancla)
    try:
        return generate_pose(these_refs, prompt)
    except Exception as e:  # noqa: BLE001
        msg = str(e).lower()
        if "moderation" not in msg and "safety" not in msg:
            raise
        safe = (build_prompt(tipo, descripcion,
                             "de pie, frontal, postura neutra y recatada",
                             anchor=con_ancla) + " " + REFUERZO_SEGURO)
        try:
            return generate_pose(these_refs, safe)
        except Exception as e2:  # noqa: BLE001
            m2 = str(e2).lower()
            if "moderation" in m2 or "safety" in m2:
                return None
            raise


def _process_job(job_id: str, reference_id: int, tipo: str,
                 descripcion: str, refs: list[bytes],
                 variant_ids: list[int] | None = None,
                 codigo: str = "") -> None:
    """Trabajo pesado (corre en un hilo del pool): OpenAI + WEBP + Odoo."""
    poses = poses_for(tipo, settings.poses_por_producto)
    total = len(poses)
    _update(job_id, estado="procesando", total=total, done=0,
            etapa=f"Generando imágenes… 0 de {total}")
    try:
        webps: list[bytes] = []
        # Anclaje de estilo: la primera imagen generada se reutiliza como
        # referencia extra en las siguientes, para que todas mantengan la misma
        # modelo, calzado, styling y colores (efecto "una sola sesión").
        anchor_png: bytes | None = None
        omitidas = 0
        for i, pose in enumerate(poses, 1):
            these_refs = refs if anchor_png is None else refs + [anchor_png]
            png = _generar_pose(these_refs, tipo, descripcion, pose,
                                anchor_png is not None)
            if png is None:                 # bloqueada por moderación: se omite
                omitidas += 1
                _update(job_id, done=i,
                        etapa=f"Pose {i}/{total} omitida (moderación)")
                continue
            if anchor_png is None:
                anchor_png = png            # la 1ª pose válida marca el estilo
            webps.append(to_webp(png, code=codigo))
            _update(job_id, done=i, etapa=f"Generando pose {i} de {total}…")

        if not webps:
            raise RuntimeError(
                "OpenAI rechazó todas las poses por moderación. "
                "Prueba con otra prenda o encuadre.")

        _update(job_id, etapa="Subiendo imágenes a Odoo…")
        odoo = get_odoo()
        if variant_ids:
            # Imágenes asignadas a las variantes del color elegido.
            odoo.set_variant_images(reference_id, variant_ids, webps)
        else:
            odoo.set_product_images(reference_id, webps)
        if settings.odoo_tag_review:
            odoo.add_tag(reference_id, settings.odoo_tag_review,
                         color=settings.odoo_tag_review_color)
        if settings.odoo_tag_ready:
            odoo.add_tag(reference_id, settings.odoo_tag_ready)

        nota = f" ({omitidas} omitidas)" if omitidas else ""
        _update(job_id, estado="listo", imagenes=len(webps), etapa="Listo" + nota)
    except Exception as e:  # noqa: BLE001
        log.exception("Fallo generando/subiendo imágenes (ref=%s, tipo=%s)",
                      reference_id, tipo)
        _update(job_id, estado="error", detail=str(e), etapa="Error")


@app.post("/api/jobs")
async def create_job(
    reference_id: int = Form(...),
    tipo: str = Form(...),
    descripcion: str = Form(...),
    frente: UploadFile = File(...),
    trasero: UploadFile = File(...),
    variant_ids: str = Form(default=""),
    codigo: str = Form(default=""),
    titulo: str = Form(default=""),
    emp: dict = Depends(require_pin),
):
    """Encola un trabajo y responde de inmediato con su job_id."""
    if tipo not in TIPOS:
        raise HTTPException(400, f"Tipo de prenda inválido: {tipo}")

    refs = [await frente.read(), await trasero.read()]
    if not all(refs):
        raise HTTPException(400, "Faltan las dos fotos (frente y trasero).")

    # Variantes del color elegido (vacío = producto sin variantes de color).
    vids = [int(x) for x in variant_ids.split(",") if x.strip().isdigit()]

    _prune()
    job_id = uuid4().hex
    now = time.time()
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "estado": "en_cola",
            "total": settings.poses_por_producto,
            "done": 0,
            "etapa": "En cola…",
            "reference_id": reference_id,
            "producto": descripcion,
            "titulo": titulo or descripcion,
            "empleado": (emp.get("name") if isinstance(emp, dict) else "") or "",
            "imagenes": 0,
            "detail": None,
            "creado": now,
            "actualizado": now,
        }
    _executor.submit(_process_job, job_id, reference_id, tipo, descripcion,
                     refs, vids, codigo)
    return {"job_id": job_id, "estado": "en_cola"}


@app.get("/api/jobs")
def list_jobs(_emp: dict = Depends(require_pin)):
    """Lista TODOS los trabajos (de cualquier operador): activos primero.

    Permite ver qué imágenes siguen pendientes de crear, y sobrevive a
    recargas de la pantalla (el estado vive en el backend).
    """
    _prune()
    with _jobs_lock:
        items = list(_jobs.values())
    orden = {"procesando": 0, "en_cola": 1, "error": 2, "listo": 3}
    items.sort(key=lambda j: (orden.get(j["estado"], 9), -j.get("creado", 0)))
    return items


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, _emp: dict = Depends(require_pin)):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Trabajo no encontrado")
    return job


# ---------- ciclo de vida de la etiqueta de revisión ----------
@app.post("/api/products/{template_id}/discard")
def discard_images(template_id: int, _emp: dict = Depends(require_pin)):
    """Descartar imágenes: las borra y quita la etiqueta de revisión."""
    odoo = get_odoo()
    odoo.clear_product_images(template_id)
    odoo.remove_tag(template_id, settings.odoo_tag_review)
    return {"ok": True}


@app.post("/api/products/{template_id}/publish")
def publish(template_id: int, _emp: dict = Depends(require_pin)):
    """Publicar: activa el toggle y quita la etiqueta de revisión."""
    odoo = get_odoo()
    odoo.set_published(template_id, True)
    odoo.remove_tag(template_id, settings.odoo_tag_review)
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True}


# ---------- PWA estática (debe ir al final) ----------
app.mount("/", StaticFiles(directory="pwa", html=True), name="pwa")
