# Plan de implementación — Alta de Productos desde la PWA

> Fase de construcción para ejecutarse **desde la sesión local** (la máquina con SSH `yoohoo-vps`
> y credenciales de Odoo). El diseño aprobado está en `alta-producto-pwa.html` (PR #6, v8) —
> úsalo como plano visual y de campos.

## Contexto

- **Odoo producción:** `https://yoohoo2.odoo.com` (SaaS 19.2), db `yoohoo2`, usuario `astf77.at@gmail.com`, API key en `credentials/yoohoo2.json` (máquina local). Conexión XML-RPC verificada.
- **PWA:** me.yoohoo.mx, backend Express en el VPS `yoohoo-vps` (72.60.24.3). Las imágenes de producto se sirven vía proxy `/api/products/:id/image` con caché y manejo de 429.
- **Diseño aprobado:** 3 fotos (proveedor opcional, delantero, trasero) · datos básicos (nombre, categoría→3 de Odoo, SKU auto, marca) · costo + 4 listas (Paquetes 13, Corridas 3, Mayoreo 4, Menudeo 15) · tallas/colores reales (frecuentes + buscador) · POS + cantidad inicial. Sin código de barras.

## Paso 0 — Revisar el proceso de imágenes existente (pedido explícito del usuario)

Las fotos delantera y trasera deben **engancharse al mismo proceso de imágenes ya alojado en la PWA**.
En el VPS, revisar el backend de la PWA unificada:

- Cómo está implementado el proxy `/api/products/:id/image` (caché, backoff 429).
- Si ya existe un endpoint/módulo de **subida** o compresión de imágenes (buscar `multer`, `sharp`, `upload`, `image` en el código del backend).
- Reutilizar ese mecanismo; si solo existe lectura, crear la subida siguiendo el mismo patrón (misma sesión Odoo, misma convención de rutas, mismo caché).

## Paso 1 — Backend: endpoint de creación

`POST /api/products` (protegido, solo perfiles autorizados):

| Campo pantalla | Odoo | Nota |
|---|---|---|
| Nombre | `product.template.name` | único obligatorio de sistema |
| Categoría | `categ_id` + `pos_categ_ids` + `public_categ_ids` | una selección llena las 3; mapear por nombre |
| SKU | `default_code` | auto: prefijo de categoría + consecutivo; validar unicidad |
| Marca | modelo de marca real (verificar; el sync usa `yh.sync.brand` en el VPS) | crear al vuelo si no existe |
| Costo | `standard_price` | |
| Menudeo | `list_price` + item en lista 15 | precio base, IVA incluido |
| Paquete/Corrida/Mayoreo | `product.pricelist.item` en listas 13/3/4 | `applied_on='1_product'`, precio fijo |
| Impuesto | `taxes_id` | IVA 16% incluido (default) |
| (oculto) | `type='consu'`, `is_storable=True`, `available_in_pos=True` | |
| Tallas/Colores | `attribute_line_ids` | atributos reales: Tallas id 10, Colour id 9; Odoo genera variantes |
| Cantidad inicial | ajuste `stock.quant` | ubicación de la tienda; si hay tallas, repartir después |

`POST /api/products/:id/images` — recibe delantera/trasera/proveedor:
- Delantera → `image_1920` del template (imagen principal: POS, catálogo, Isabela, sync web).
- Trasera y proveedor → registros `product.image` (galería; el sync WooCommerce ya la consume por hashes).
- Comprimir en el cliente antes de subir (canvas: máx ~1600 px lado largo, JPEG ~0.8) — fotos de celular pesan 5–12 MB y Odoo SaaS rate-limita.

Validaciones servidor: SKU único, 4 precios > 0, margen negativo → advertencia, nombre no vacío.

## Paso 2 — Frontend PWA

Pantalla "Alta de productos" replicando el mockup:
- Bloques: 📷 Fotos (3 slots con cámara) → 🏷️ Datos básicos → 💲 Precios (margen por lista en vivo) → 📏 Tallas y variantes → 🛒 POS/inventario.
- Tallas y colores **desde la API en vivo** (no hardcodear): endpoint que devuelva atributos + valores + frecuencia de uso; patrón frecuentes + hoja con buscador; orden de tallas: letras XS→XS/S→S→S/M→M→M/L→L→L/XL→XL→XXL, números ascendentes, 1X–4X al final de los números; grupos de corrida validados contra el uso real en Odoo: **Dama 1–15** (impares), **Blusas (letras)** XS–XXL y combinadas, **Extras** (16–24, 17/19 y 1X–4X), **Pants 28–40**, **Pares 0–14**, **Unitalla** — cada uno con "toda la corrida".
- Resumen antes de confirmar + pantalla de éxito con "dar de alta otro".
- Acceso solo para perfiles autorizados (Aaron/admin y encargado de inventario), mismo esquema de PIN/roles actual.
- Bump del service worker al desplegar.

## Paso 3 — Verificación end-to-end

1. Crear un producto de prueba completo (fotos + tallas + 4 precios) desde el teléfono.
2. Verificar: aparece en POS, imágenes por el proxy, variantes correctas, precios en las 4 listas, margen.
3. Verificar propagación: catálogo Captura de Pedidos, Isabela (foto por WhatsApp), sync web.
4. Archivar/eliminar el producto de prueba.

## Pendiente relacionado (aparte)

Limpieza de catálogo detectada al jalar los datos: talla "0" duplicada; "Unitalla"/"UNITALLA"/"Única"/"CERO" (4 registros); "khaki"/"Khaki"; "camel"/"Camel"; "Black"/"Negro"; "White"/"Blanco"; categoría POS "BLUSA SI VOY OERO ME CHOCA". Unificar antes o después del alta, cuidando variantes existentes.
