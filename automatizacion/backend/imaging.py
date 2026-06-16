"""Procesado de imágenes: recorte a 800x1000 y exportación a WEBP <=100KB."""
from __future__ import annotations

import io

from PIL import Image

from .config import settings


def to_webp(png_bytes: bytes) -> bytes:
    """Recorta al ratio destino (cover + center crop) y exporta WEBP ligero."""
    target_w, target_h = settings.img_ancho, settings.img_alto
    max_bytes = settings.img_max_kb * 1024

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")

    # Escalar tipo "cover" y recortar al centro al ratio destino.
    src_ratio = img.width / img.height
    dst_ratio = target_w / target_h
    if src_ratio > dst_ratio:
        new_h = target_h
        new_w = round(target_h * src_ratio)
    else:
        new_w = target_w
        new_h = round(target_w / src_ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))

    # Bajar la calidad hasta cumplir el límite de peso.
    for quality in range(90, 30, -5):
        out = io.BytesIO()
        img.save(out, format="WEBP", quality=quality, method=6)
        if out.tell() <= max_bytes:
            return out.getvalue()
    return out.getvalue()  # mejor esfuerzo si no baja de 100KB
