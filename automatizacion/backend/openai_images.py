"""Generación de imágenes con la API de OpenAI (gpt-image-1).

Usa el endpoint de edición de imágenes: recibe las fotos de referencia
(frente y trasero) + un prompt por pose y devuelve la imagen generada.
"""
from __future__ import annotations

import base64
import io

from openai import OpenAI

from .config import settings
from .imaging import to_png_reference

_client: OpenAI | None = None


def _client_singleton() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


def _build_files(reference_images: list[bytes]) -> list:
    files = []
    for idx, img in enumerate(reference_images):
        bio = io.BytesIO(to_png_reference(img))   # PNG real (nombre y contenido coinciden)
        bio.name = f"ref-{idx}.png"
        files.append(bio)
    return files


def generate_pose(reference_images: list[bytes], prompt: str) -> bytes:
    """Genera una imagen PNG a partir de las referencias + prompt.

    Genera en tamaño retrato 1024x1536; el recorte final a 800x1000 lo hace
    el módulo imaging.py. Intenta con la calidad configurada y, si la API no
    acepta ese parámetro, reintenta sin él (no rompe la generación).
    """
    client = _client_singleton()
    base = dict(model=settings.openai_image_model, prompt=prompt,
                size="1024x1536", n=1)
    q = (settings.openai_image_quality or "").strip().lower()

    try:
        extra = {"quality": q} if q and q != "auto" else {}
        result = client.images.edit(image=_build_files(reference_images),
                                    **extra, **base)
    except Exception as e:  # noqa: BLE001
        msg = str(e).lower()
        # La moderación la maneja el worker (reintento/omitir): propágala.
        if "moderation" in msg or "safety" in msg:
            raise
        # Si el 400 es por el parámetro quality, reintenta sin él.
        if q and "quality" in msg:
            result = client.images.edit(image=_build_files(reference_images), **base)
        else:
            raise
    return base64.b64decode(result.data[0].b64_json)
