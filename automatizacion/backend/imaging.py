"""Procesado de imágenes: recorte a 800x1000 y exportación a WEBP <=100KB."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .config import settings

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _load_font(size: int):
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def stamp_code(img: "Image.Image", code: str) -> "Image.Image":
    """Estampa el código del producto de forma discreta (abajo a la derecha).

    Chip translúcido oscuro con el código en blanco: lo bastante nítido para
    que un chatbot lo lea por OCR y el personal lo identifique, sin invadir la
    prenda.
    """
    code = (str(code or "")).strip()
    if not code:
        return img
    W, H = img.size
    size = max(14, W // 40)                     # ~20px con 800 de ancho
    font = _load_font(size)
    base = img.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    try:
        bbox = d.textbbox((0, 0), code, font=font)
    except Exception:  # noqa: BLE001
        bbox = (0, 0, len(code) * size // 2, size)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = max(4, size // 3)
    margin = max(6, size // 2)
    x2, y2 = W - margin, H - margin
    x1, y1 = x2 - tw - 2 * pad, y2 - th - 2 * pad
    if hasattr(d, "rounded_rectangle"):
        d.rounded_rectangle([x1, y1, x2, y2], radius=max(4, size // 4),
                            fill=(0, 0, 0, 115))
    else:
        d.rectangle([x1, y1, x2, y2], fill=(0, 0, 0, 115))
    d.text((x1 + pad - bbox[0], y1 + pad - bbox[1]), code,
           font=font, fill=(255, 255, 255, 235))
    return Image.alpha_composite(base, overlay).convert("RGB")


def to_png_reference(raw: bytes, max_side: int = 1536) -> bytes:
    """Normaliza una foto de entrada a PNG real para enviarla a OpenAI.

    Las fotos del teléfono llegan en JPEG (u otros) y a veces con orientación
    EXIF o tamaño grande; OpenAI rechaza (400) si el contenido no es un formato
    válido o pesa demasiado. Aquí: corrige orientación, pasa a RGB, reduce el
    lado mayor a `max_side` y exporta PNG.
    """
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)        # respeta orientación de la cámara
    img = img.convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def to_webp(png_bytes: bytes, code: str | None = None) -> bytes:
    """Recorta al ratio destino (cover + center crop) y exporta WEBP ligero.

    Si se pasa `code`, lo estampa de forma discreta (para OCR del chatbot).
    """
    target_w, target_h = settings.img_ancho, settings.img_alto
    max_bytes = settings.img_max_kb * 1024

    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")

    # "Contain": encaja la imagen COMPLETA (sin recortar la prenda ni el
    # calzado) y rellena los lados con el color del fondo del estudio
    # (muestreado de una esquina), para no perder cabeza ni pies al ajustar
    # a 800x1000.
    scale = min(target_w / img.width, target_h / img.height)
    new_w = max(1, round(img.width * scale))
    new_h = max(1, round(img.height * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    fondo = img.getpixel((1, 1))          # color del fondo (esquina superior izq.)
    lienzo = Image.new("RGB", (target_w, target_h), fondo)
    lienzo.paste(img, ((target_w - new_w) // 2, (target_h - new_h) // 2))
    img = lienzo

    if code:
        img = stamp_code(img, code)

    # Bajar la calidad hasta cumplir el límite de peso.
    for quality in range(90, 30, -5):
        out = io.BytesIO()
        img.save(out, format="WEBP", quality=quality, method=6)
        if out.tell() <= max_bytes:
            return out.getvalue()
    return out.getvalue()  # mejor esfuerzo si no baja de 100KB
