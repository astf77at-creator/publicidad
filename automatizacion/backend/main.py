"""API FastAPI que orquesta: PWA -> OpenAI -> Odoo.

Flujo principal (POST /api/jobs):
  1. Recibe 2 fotos (frente + trasero) + referencia elegida + tipo de prenda.
  2. Genera N poses con OpenAI usando las fotos como referencia.
  3. Convierte cada pose a WEBP 800x1000 <=100KB.
  4. Sube las imágenes al producto en Odoo.
  5. Añade etiquetas "Revisión de imágenes" + "Listo".
"""
from __future__ import annotations

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .imaging import to_webp
from .odoo import get_odoo
from .openai_images import generate_pose
from .prompts import TIPOS, build_prompt, poses_for

app = FastAPI(title="Automatización de imágenes de producto")


# ---------- catálogos / cascada ----------
@app.get("/api/tipos")
def tipos():
    return [{"id": k, "label": v["label"]} for k, v in TIPOS.items()]


@app.get("/api/categories")
def categories():
    return get_odoo().get_categories()


@app.get("/api/brands")
def brands(category_id: int):
    return get_odoo().get_brands(category_id)


@app.get("/api/references")
def references(category_id: int, brand: str):
    val: str | int = int(brand) if brand.isdigit() else brand
    return get_odoo().get_references(category_id, val)


# ---------- orquestación ----------
@app.post("/api/jobs")
async def create_job(
    reference_id: int = Form(...),
    tipo: str = Form(...),
    descripcion: str = Form(...),
    frente: UploadFile = File(...),
    trasero: UploadFile = File(...),
):
    if tipo not in TIPOS:
        raise HTTPException(400, f"Tipo de prenda inválido: {tipo}")

    refs = [await frente.read(), await trasero.read()]
    if not all(refs):
        raise HTTPException(400, "Faltan las dos fotos (frente y trasero).")

    poses = poses_for(tipo, settings.poses_por_producto)
    webps: list[bytes] = []
    for pose in poses:
        prompt = build_prompt(tipo, descripcion, pose)
        png = generate_pose(refs, prompt)
        webps.append(to_webp(png))

    odoo = get_odoo()
    odoo.set_product_images(reference_id, webps)
    odoo.add_tag(reference_id, settings.odoo_tag_review)
    odoo.add_tag(reference_id, settings.odoo_tag_ready)

    return JSONResponse({"ok": True, "reference_id": reference_id, "imagenes": len(webps)})


# ---------- ciclo de vida de la etiqueta de revisión ----------
@app.post("/api/products/{template_id}/discard")
def discard_images(template_id: int):
    """Descartar imágenes: las borra y quita la etiqueta de revisión."""
    odoo = get_odoo()
    odoo.clear_product_images(template_id)
    odoo.remove_tag(template_id, settings.odoo_tag_review)
    return {"ok": True}


@app.post("/api/products/{template_id}/publish")
def publish(template_id: int):
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
