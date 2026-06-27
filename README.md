# Publicidad y marketing — YooHoo

Proyecto para crear **anuncios y marketing de YooHoo** (moda para dama), trabajando
**en la nube y desde el celular**, sin depender de la PC.

## Cómo funciona (en la nube, desde el celular)

1. La identidad de la marca vive en [`MARCA-YOOHOO.md`](MARCA-YOOHOO.md) — fuente única
   de verdad para que todo anuncio salga consistente.
2. Los anuncios se crean en **Canva** (100% en la nube, editables desde el celular).
3. Desde Claude Code en la web (en tu celular) pides: *"haz un anuncio de YooHoo para
   [promoción/producto]"* → se genera el diseño en tu cuenta de Canva.
4. Abres Canva en el celular, ajustas foto/texto y publicas.

## Archivos

- [`MARCA-YOOHOO.md`](MARCA-YOOHOO.md) — guía de marca (colores, contacto, tono, tallas, CTAs).
- `flyer.html` — plantilla de flyer autocontenida (A4) como referencia para imprimir/exportar a PDF.

## Cómo personalizarlo

Abre `flyer.html` y reemplaza los textos de ejemplo:

| Marcador | Dónde aparece | Qué poner |
|----------|---------------|-----------|
| `NOMBRE DE TU APP` | cabecera | El nombre real de la app |
| Titular y subtítulo | cabecera (`<h1>`, `.lead`) | Tu mensaje principal |
| Beneficios | sección `.beneficios` | Las 4 ventajas reales de la app |
| Botones de tienda | `.stores` | Enlaces a App Store / Google Play |
| Código QR | `.qr .caja` | Sustituye el SVG por un QR real que apunte a tu enlace de descarga |
| Pie de página | `.pie` | Web, teléfono y redes sociales |

> El QR incluido es **decorativo**. Genera uno real (p. ej. en un generador de QR) que apunte al enlace de descarga y pégalo en lugar del `<svg>`.

## Cómo exportarlo

1. Abre `flyer.html` en el navegador.
2. `Ctrl/Cmd + P` → **Guardar como PDF**.
3. Ajustes recomendados: tamaño A4, márgenes "Ninguno", activar "Gráficos de fondo".

También puedes hacer una captura de pantalla para compartirlo en redes sociales o WhatsApp.
