# Automatización de imágenes de producto

Backend + PWA para generar las imágenes de producto automáticamente:

1. En la **PWA** subes 2 fotos (frente + trasero) del producto.
2. Eliges en cascada **Tipo de prenda → Categoría → Marca → Referencia**
   (Categoría/Marca/Referencia se leen de Odoo).
3. El **backend** envía las fotos + el prompt correcto (según el tipo de prenda)
   a la API de OpenAI (`gpt-image-1`).
4. Convierte cada pose a **WEBP 800×1000 ≤100 KB**.
5. Sube las imágenes al producto en Odoo (por su Referencia).
6. Añade en Odoo las etiquetas **"Revisión de imágenes"** + **"Listo"**.
7. La etiqueta "Revisión de imágenes" se quita cuando:
   - se **descartan** las imágenes (`POST /api/products/{id}/discard`), o
   - se **publica** el producto (`POST /api/products/{id}/publish`, activa el toggle).

## Arquitectura

```
VPS:  PWA  ──►  Backend FastAPI  ──►  OpenAI gpt-image-1
                      │
                      └──►  Odoo (API externa XML-RPC)
```

Producción es Odoo Online (SaaS, sin módulos custom), por eso toda la lógica
vive en el backend del VPS y habla con Odoo solo por su API externa estándar.
Para probar sin riesgo, apunta `ODOO_URL` al **Odoo espejo** del VPS.

## Puesta en marcha

```bash
cd automatizacion
cp .env.example .env      # rellena credenciales de Odoo y OpenAI
docker compose up --build # arranca en http://localhost:8080
```

Sin Docker:

```bash
cd automatizacion
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # rellena credenciales
uvicorn backend.main:app --host 0.0.0.0 --port 8080
```

Abre `http://TU_VPS:8080` en el móvil y, si quieres, "Añadir a pantalla de inicio"
para instalarla como app.

## Configuración importante (`.env`)

| Variable | Qué es |
|----------|--------|
| `ODOO_URL` / `ODOO_DB` / `ODOO_USERNAME` / `ODOO_API_KEY` | Conexión a Odoo (espejo o producción) |
| `ODOO_BRAND_FIELD` | **Campo de la marca en tu Odoo** (no es estándar; ajústalo) |
| `ODOO_CATEGORY_FIELD` / `ODOO_REFERENCE_FIELD` / `ODOO_PUBLISHED_FIELD` | Campos de categoría / referencia / publicación |
| `ODOO_TAG_REVIEW` / `ODOO_TAG_READY` | Nombres de las etiquetas |
| `OPENAI_API_KEY` | Clave de OpenAI con acceso a `gpt-image-1` |
| `POSES_POR_PRODUCTO` | Cuántas imágenes generar (5–8) |

## Pendiente de confirmar con tu Odoo

El código asume modelos/campos estándar de Odoo y los hace configurables. Hay
que confirmar contra tu instancia:

- **Marca**: ¿en qué campo está? (`product_brand_id`, `x_studio_marca`, …)
- **Categoría**: ¿`categ_id` o un campo propio?
- **Etiquetas**: ¿usan el modelo `product.tag`? Nombre exacto de "Listo".
- **Publicar**: ¿es `is_published` (módulo web/eCommerce) u otro toggle?

Ver `backend/odoo.py` y `.env.example`.
