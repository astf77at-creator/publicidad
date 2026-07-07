# Motor de Alta de Productos — PWA YOOHOO

Backend real (validado end-to-end contra `yoohoo2.odoo.com`) para dar de alta
productos desde la PWA. Es la lógica que el backend de la PWA invocará; la UI
está en `../alta-producto-pwa.html`.

## Estado: ✅ VALIDADO

Se probó creando un producto real completo en Odoo de producción y verificando
los 15 puntos (nombre, SKU, 3 categorías, 4 precios, costo, sin impuesto,
almacenable+POS, marca, 6 variantes talla×color, foto principal, galería,
stock inicial). El producto de prueba se archivó al terminar.

## Archivos

- `crear_producto.py` — motor `crear_producto(models, uid, key, spec)`.
- `categoria_map.json` — mapeo categoría interna → POS/eCommerce por uso real.

## `spec` de entrada

```python
spec = {
  "nombre": "Blusa manga larga rayas",   # obligatorio
  "categoria": "Blusas",                 # nombre; llena categ_id + pos + public
  "sku": "BLU-123",                      # default_code (identificador POS)
  "marca": "YOO HOO",                    # se crea en x_marca si no existe
  "costo": 80.0,                         # standard_price (por variante)
  "precios": {"paquete":150,"corrida":165,"mayoreo":180,"menudeo":220},
  "pos": True,
  "tallas": ["S","M","L"],               # crea variantes
  "colores": ["Negro","Blanco"],
  "foto_delantera": "<base64 jpg>",      # image_1920 (principal)
  "galeria": [{"name":"Trasera","data":"<b64>"}, {"name":"Proveedor","data":"<b64>"}],
  "cantidad_inicial": 5, "location_id": <id ubicacion tienda>,  # opcional
}
```

## Mapeo real verificado en yoohoo2 (Odoo SaaS 19.2)

| Campo pantalla | Campo Odoo | Nota descubierta al validar |
|---|---|---|
| Nombre | `product.template.name` | único obligatorio de sistema |
| Categoría | `categ_id` + `pos_categ_ids` + `public_categ_ids` | son **3 IDs independientes**; se resuelven por nombre (ver `categoria_map.json`) |
| SKU | `default_code` | identificador para POS (no usan código de barras) |
| **Marca** | `x_studio_marca_id` → modelo **`x_marca`** (campo `x_name`) | campo Studio; se crea la marca si no existe |
| Costo | `standard_price` | **se escribe por variante** (`product.product`), no en el template |
| Menudeo | `list_price` | precio base |
| Paquete/Corrida/Mayoreo | `product.pricelist.item` (`applied_on='1_product'`, `compute_price='fixed'`) | listas **13 / 3 / 4**; menudeo es lista 15 = `list_price` |
| Impuesto | `taxes_id` | **vacío**: los productos reales de yoohoo2 no llevan impuesto |
| Tipo | `type='consu'` + `is_storable=True` | almacenable |
| POS | `available_in_pos=True` | |
| Tallas / Colores | `attribute_line_ids` (attr **10** Tallas, **9** Colour) | Odoo genera las variantes |
| Cantidad inicial | `stock.quant` + `action_apply_inventory` | requiere aplicar el conteo |

## Gotchas resueltos (importantes para el backend PWA)

1. **429 Too Many Requests** — Odoo SaaS rate-limita las ráfagas (sobre todo con
   imágenes). El motor reintenta con backoff exponencial (2,4,8,16s). El backend
   de la PWA debe conservar esto.
2. **Costo por variante** — `standard_price` en el template no se propaga; se
   escribe en cada `product.product`.
3. **Inventario** — `stock.quant.inventory_quantity` queda pendiente hasta
   `action_apply_inventory` (que devuelve `None`; XML-RPC no serializa `None`,
   se tolera el Fault: el conteo ya se aplicó).
4. **Imágenes** — deben ir en base64 de un JPEG/PNG válido; comprimir en cliente
   (~600–1600 px) antes de subir para no disparar el 429.
5. **Borrado** — un producto con sesión POS abierta no se puede borrar; la PWA
   debe **archivar** (`active=False`), no eliminar.

## Pendiente (requiere acceso al VPS, no disponible en el entorno remoto)

- Envolver `crear_producto` en el endpoint del backend Express de la PWA
  (`POST /api/products`), reusando su sesión Odoo y su proxy de imágenes.
- Pantalla en la PWA (base ya diseñada en `../alta-producto-pwa.html`), tallas
  y colores servidos en vivo desde un endpoint de atributos.
- Restringir por perfil (Aaron / encargado de inventario).
