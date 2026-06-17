"""API FastAPI que orquesta: PWA -> OpenAI -> Odoo.

Flujo principal (POST /api/jobs):
  1. Recibe 2 fotos (frente + trasero) + referencia elegida + tipo de prenda.
  2. Genera N poses con OpenAI usando las fotos como referencia.
  3. Convierte cada pose a WEBP 800x1000 <=100KB.
  4. Sube las imágenes al producto en Odoo.
  5. Añade etiquetas "Revisión de imágenes" + "Listo".
"""
from __future__ import annotations

import json
import logging

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .imaging import to_webp
from .odoo import get_auth_odoo, get_odoo
from .openai_images import generate_pose
from .prompts import TIPOS, build_prompt, poses_for

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


# ---------- orquestación ----------
@app.post("/api/jobs")
async def create_job(
    reference_id: int = Form(...),
    tipo: str = Form(...),
    descripcion: str = Form(...),
    frente: UploadFile = File(...),
    trasero: UploadFile = File(...),
    _emp: dict = Depends(require_pin),
):
    if tipo not in TIPOS:
        raise HTTPException(400, f"Tipo de prenda inválido: {tipo}")

    refs = [await frente.read(), await trasero.read()]
    if not all(refs):
        raise HTTPException(400, "Faltan las dos fotos (frente y trasero).")

    poses = poses_for(tipo, settings.poses_por_producto)

    # Respuesta en streaming (NDJSON): un evento por pose para que el front
    # muestre una barra de avance real en vez de quedarse "congelado".
    def stream():
        def ev(obj: dict) -> bytes:
            return (json.dumps(obj) + "\n").encode()
        try:
            total = len(poses)
            yield ev({"stage": "start", "total": total})
            webps: list[bytes] = []
            for i, pose in enumerate(poses, 1):
                prompt = build_prompt(tipo, descripcion, pose)
                png = generate_pose(refs, prompt)
                webps.append(to_webp(png))
                yield ev({"stage": "pose", "done": i, "total": total})
            yield ev({"stage": "uploading"})
            odoo = get_odoo()
            odoo.set_product_images(reference_id, webps)
            if settings.odoo_tag_review:
                odoo.add_tag(reference_id, settings.odoo_tag_review,
                             color=settings.odoo_tag_review_color)
            if settings.odoo_tag_ready:
                odoo.add_tag(reference_id, settings.odoo_tag_ready)
            yield ev({"stage": "done", "ok": True,
                      "reference_id": reference_id, "imagenes": len(webps)})
        except Exception as e:  # noqa: BLE001
            log.exception("Fallo generando/subiendo imágenes (ref=%s, tipo=%s)",
                          reference_id, tipo)
            yield ev({"stage": "error", "detail": str(e)})

    return StreamingResponse(stream(), media_type="application/x-ndjson")


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
