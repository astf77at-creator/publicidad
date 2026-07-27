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


def generate_pose(reference_images: list[bytes], prompt: str) -> bytes:
    """Genera una imagen PNG a partir de las referencias + prompt.

    Genera en tamaño retrato 1024x1536; el recorte final a 800x1000 lo hace
    el módulo imaging.py.
    """
    client = _client_singleton()
    files = []
    for idx, img in enumerate(reference_images):
        bio = io.BytesIO(to_png_reference(img))   # PNG real (nombre y contenido coinciden)
        bio.name = f"ref-{idx}.png"
        files.append(bio)

    result = client.images.edit(
        model=settings.openai_image_model,
        image=files,
        prompt=prompt,
        size="1024x1536",
        quality=settings.openai_image_quality,   # "high" = más fotorrealista
        n=1,
    )
    return base64.b64decode(result.data[0].b64_json)
