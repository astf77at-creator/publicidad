# Flyer publicitario — App

Flyer publicitario en HTML/CSS para invitar a los clientes a descargar y usar nuestra app.

## Archivos

- `flyer.html` — flyer autocontenido (sin dependencias), tamaño A4, listo para imprimir o exportar a PDF.
- `alta-producto-pwa.html` — propuesta de diseño (mockup interactivo) de la pantalla de alta de productos para la PWA de YOOHOO: análisis de campos obligatorios de Odoo, interfase móvil funcional como demo y mapeo técnico de campos a `product.template`. Ábrelo en el navegador y prueba el formulario.

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
