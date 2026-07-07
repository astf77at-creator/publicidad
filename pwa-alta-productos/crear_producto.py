"""
Motor de alta de productos para YOOHOO (yoohoo2.odoo.com) — lógica real que
la PWA invocará desde su backend. Escrito y probado por XML-RPC.

Uso: crear_producto(models, uid, spec) -> {template_id, variant_ids, ...}
"""
import xmlrpc.client, os, base64, time

URL, DB, USER = "https://yoohoo2.odoo.com", "yoohoo2", "astf77.at@gmail.com"

# IDs reales verificados en yoohoo2
ATTR_TALLA = 10
ATTR_COLOR = 9
PRICELIST = {"paquete": 13, "corrida": 3, "mayoreo": 4, "menudeo": 15}  # menudeo = list_price base
MARCA_MODEL = "x_marca"

def conectar(key):
    uid = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common").authenticate(DB, USER, key, {})
    models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")
    return uid, models

def _call(models, uid, key, model, method, *args, **kw):
    """Llamada XML-RPC con reintento y backoff ante el 429 de Odoo SaaS."""
    delay = 2
    for intento in range(5):
        try:
            return models.execute_kw(DB, uid, key, model, method, list(args), kw)
        except xmlrpc.client.ProtocolError as e:
            if e.errcode == 429 and intento < 4:
                time.sleep(delay); delay *= 2; continue
            raise


def resolver_categoria(c, uid, key, nombre_interna):
    """Devuelve (categ_id, [pos_ids], [public_ids]) resolviendo por nombre.
    Si no encuentra POS/public equivalente, crea/deja solo la interna."""
    cat = c("product.category", "search", [["name", "=", nombre_interna]], limit=1)
    categ_id = cat[0] if cat else c("product.category", "create", {"name": nombre_interna})
    pos = c("pos.category", "search", [["name", "=", nombre_interna]], limit=1)
    pub = c("product.public.category", "search", [["name", "=", nombre_interna]], limit=1)
    pos_ids = pos or [c("pos.category", "create", {"name": nombre_interna})]
    pub_ids = pub or [c("product.public.category", "create", {"name": nombre_interna})]
    return categ_id, pos_ids, pub_ids


def resolver_marca(c, uid, key, nombre):
    if not nombre:
        return False
    m = c(MARCA_MODEL, "search", [["x_name", "=", nombre]], limit=1)
    return m[0] if m else c(MARCA_MODEL, "create", {"x_name": nombre})


def _valores_attr(c, attr_id, nombres):
    """Devuelve los IDs de product.attribute.value creando los que falten."""
    ids = []
    for n in nombres:
        v = c("product.attribute.value", "search",
              [["attribute_id", "=", attr_id], ["name", "=", n]], limit=1)
        ids.append(v[0] if v else c("product.attribute.value", "create",
                                    {"attribute_id": attr_id, "name": n}))
    return ids


def crear_producto(models, uid, key, spec):
    c = lambda *a, **k: _call(models, uid, key, *a, **k)
    categ_id, pos_ids, pub_ids = resolver_categoria(c, uid, key, spec["categoria"])
    marca_id = resolver_marca(c, uid, key, spec.get("marca"))

    # Líneas de atributo (tallas / colores)
    attr_lines = []
    if spec.get("tallas"):
        attr_lines.append((0, 0, {"attribute_id": ATTR_TALLA,
                                  "value_ids": [(6, 0, _valores_attr(c, ATTR_TALLA, spec["tallas"]))]}))
    if spec.get("colores"):
        attr_lines.append((0, 0, {"attribute_id": ATTR_COLOR,
                                  "value_ids": [(6, 0, _valores_attr(c, ATTR_COLOR, spec["colores"]))]}))

    vals = {
        "name": spec["nombre"],
        "categ_id": categ_id,
        "pos_categ_ids": [(6, 0, pos_ids)],
        "public_categ_ids": [(6, 0, pub_ids)],
        "default_code": spec.get("sku") or False,
        "standard_price": spec.get("costo", 0.0),
        "list_price": spec["precios"]["menudeo"],   # menudeo = precio base
        "taxes_id": [(6, 0, [])],                    # productos yoohoo2 sin impuesto (patrón real)
        "type": "consu",
        "is_storable": True,
        "available_in_pos": bool(spec.get("pos", True)),
        "attribute_line_ids": attr_lines,
    }
    if marca_id:
        vals["x_studio_marca_id"] = marca_id
    if spec.get("foto_delantera"):
        vals["image_1920"] = spec["foto_delantera"]

    tmpl_id = c("product.template", "create", vals)

    # Reglas de precio en las 3 listas restantes (menudeo ya es list_price)
    for lista in ("paquete", "corrida", "mayoreo"):
        precio = spec["precios"].get(lista)
        if precio:
            c("product.pricelist.item", "create", {
                "pricelist_id": PRICELIST[lista],
                "applied_on": "1_product",
                "product_tmpl_id": tmpl_id,
                "compute_price": "fixed",
                "fixed_price": precio,
                "min_quantity": 0,
            })

    # Galería (trasera + proveedor)
    for img in (spec.get("galeria") or []):
        c("product.image", "create", {"product_tmpl_id": tmpl_id, "name": img["name"], "image_1920": img["data"]})

    variant_ids = c("product.product", "search", [["product_tmpl_id", "=", tmpl_id]])

    # Costo: standard_price se almacena por variante en Odoo 19
    if spec.get("costo"):
        c("product.product", "write", variant_ids, {"standard_price": spec["costo"]})

    # Inventario inicial (opcional) en la ubicación de la tienda
    if spec.get("cantidad_inicial") and spec.get("location_id"):
        quant_ids = []
        for vid in variant_ids:
            q = c("stock.quant", "create", {
                "product_id": vid, "location_id": spec["location_id"],
                "inventory_quantity": spec["cantidad_inicial"],
            })
            quant_ids.append(q)
        # Aplicar el conteo (Odoo 19 lo deja pendiente hasta validar).
        # El método aplica el inventario como efecto y devuelve None; XML-RPC
        # no serializa None, así que toleramos ese Fault (el conteo ya se aplicó).
        try:
            c("stock.quant", "action_apply_inventory", quant_ids)
        except xmlrpc.client.Fault as e:
            if "marshal None" not in str(e):
                raise

    return {"template_id": tmpl_id, "variant_ids": variant_ids,
            "categ_id": categ_id, "pos_ids": pos_ids, "public_ids": pub_ids, "marca_id": marca_id}
