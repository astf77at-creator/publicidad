"""Cliente de Odoo vía API externa XML-RPC.

Funciona con Odoo Online (SaaS) y con el Odoo espejo del VPS sin instalar
módulos: solo usa los endpoints estándar /xmlrpc/2/common y /xmlrpc/2/object.
"""
from __future__ import annotations

import base64
import logging
import threading
import xmlrpc.client
from functools import lru_cache

from .config import settings

log = logging.getLogger(__name__)


class OdooClient:
    def __init__(self, url: str | None = None, db: str | None = None,
                 username: str | None = None, api_key: str | None = None) -> None:
        self.url = (url or settings.odoo_url).rstrip("/")
        self.db = db or settings.odoo_db
        self.username = username or settings.odoo_username
        self.api_key = api_key or settings.odoo_api_key
        self._uid: int | None = None
        self._uid_lock = threading.Lock()
        self._model_exists: dict[str, bool] = {}

    # ---- autenticación ----
    @property
    def uid(self) -> int:
        # Double-checked locking: autentica UNA sola vez aunque lleguen muchas
        # peticiones concurrentes. Sin esto, una ráfaga dispara N authenticate
        # simultáneos y Odoo Online responde 429 Too Many Requests.
        if self._uid is None:
            with self._uid_lock:
                if self._uid is None:
                    common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
                    self._uid = common.authenticate(
                        self.db, self.username, self.api_key, {})
                    if not self._uid:
                        raise RuntimeError(
                            "No se pudo autenticar en Odoo. Revisa credenciales.")
        return self._uid

    def execute(self, model: str, method: str, *args, **kwargs):
        # ServerProxy NUEVO por llamada: xmlrpc.client reutiliza una sola
        # conexión HTTP por proxy y NO es thread-safe; compartirla entre
        # peticiones concurrentes corrompe la conexión (CannotSendRequest).
        models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")
        return models.execute_kw(
            self.db, self.uid, self.api_key, model, method, list(args), kwargs or {}
        )

    def has_model(self, model: str) -> bool:
        """¿Existe este modelo en la instancia? (cacheado).

        Permite degradar con elegancia en instancias sin website_sale, donde
        el modelo product.image (imágenes extra) no está disponible.
        """
        if model not in self._model_exists:
            self._model_exists[model] = bool(
                self.execute("ir.model", "search_count", [["model", "=", model]])
            )
        return self._model_exists[model]

    # ---- selección en cascada ----
    def get_categories(self) -> list[dict]:
        """Categorías de producto usadas (product.category)."""
        return self.execute("product.category", "search_read", [], fields=["id", "name"])

    def get_brands(self, category_id: int) -> list[dict]:
        """Marcas distintas presentes en los productos de una categoría."""
        field = settings.odoo_brand_field
        recs = self.execute(
            "product.template", "search_read",
            [[settings.odoo_category_field, "=", category_id]],
            fields=[field],
        )
        marcas: dict[int, str] = {}
        for r in recs:
            val = r.get(field)
            if isinstance(val, (list, tuple)) and len(val) == 2:  # many2one [id, name]
                marcas[val[0]] = val[1]
            elif val:  # texto plano
                marcas[hash(val)] = val
        return [{"id": k, "name": v} for k, v in sorted(marcas.items(), key=lambda x: x[1])]

    def get_references(self, category_id: int, brand: str | int) -> list[dict]:
        """Referencias (productos) de una categoría + marca."""
        domain = [[settings.odoo_category_field, "=", category_id]]
        field = settings.odoo_brand_field
        if isinstance(brand, int):
            domain.append([field, "=", brand])
        else:
            domain.append([field, "=", brand])
        return self.execute(
            "product.template", "search_read", domain,
            fields=["id", "name", settings.odoo_reference_field],
        )

    # ---- imágenes ----
    def set_product_images(self, template_id: int, images_png: list[bytes]) -> None:
        """Asigna la primera imagen como principal y el resto como extras."""
        if not images_png:
            return
        principal = base64.b64encode(images_png[0]).decode()
        self.execute("product.template", "write", [template_id], {"image_1920": principal})
        extras = images_png[1:]
        if extras and not self.has_model("product.image"):
            log.warning(
                "product.image no existe en esta instancia (sin website_sale): "
                "guardada solo la imagen principal; se omiten %d poses extra.",
                len(extras),
            )
            return
        for idx, img in enumerate(extras, start=1):
            self.execute("product.image", "create", {
                "name": f"pose-{idx}",
                "image_1920": base64.b64encode(img).decode(),
                "product_tmpl_id": template_id,
            })

    def clear_product_images(self, template_id: int) -> None:
        """Borra imágenes (descartadas): principal + extras."""
        self.execute("product.template", "write", [template_id], {"image_1920": False})
        if not self.has_model("product.image"):
            return
        extra_ids = self.execute(
            "product.image", "search", [["product_tmpl_id", "=", template_id]]
        )
        if extra_ids:
            self.execute("product.image", "unlink", extra_ids)

    # ---- etiquetas (product.tag) ----
    def _tag_id(self, name: str, create: bool = True,
                color: str | None = None) -> int | None:
        ids = self.execute("product.tag", "search", [["name", "=", name]], limit=1)
        if ids:
            tid = ids[0]
            if color:  # asegurar el color pedido (corrige el por defecto)
                cur = self.execute("product.tag", "read", [tid],
                                   fields=["color"])[0].get("color")
                if cur != color:
                    self.execute("product.tag", "write", [tid], {"color": color})
            return tid
        if create:
            vals = {"name": name}
            if color:
                vals["color"] = color
            return self.execute("product.tag", "create", vals)
        return None

    def add_tag(self, template_id: int, name: str, color: str | None = None) -> None:
        tid = self._tag_id(name, color=color)
        self.execute("product.template", "write", [template_id],
                     {"product_tag_ids": [(4, tid)]})

    def remove_tag(self, template_id: int, name: str) -> None:
        tid = self._tag_id(name, create=False)
        if tid:
            self.execute("product.template", "write", [template_id],
                         {"product_tag_ids": [(3, tid)]})

    # ---- publicación ----
    def set_published(self, template_id: int, published: bool) -> None:
        self.execute("product.template", "write", [template_id],
                     {settings.odoo_published_field: published})

    # ---- productos SIN imagen, priorizados por stock ----
    def products_missing_images(self, limit: int = 1000) -> list[dict]:
        """Productos sin imagen principal y con piezas disponibles.

        Devuelve [{id, name, default_code, categoria, qty}] ordenado por
        categoría/subcategoría (complete_name del categ_id) y, dentro de cada
        una, de mayor a menor cantidad disponible.
        """
        domain = [["image_1920", "=", False], ["qty_available", ">", 0]]
        recs = self.execute(
            "product.template", "search_read", domain,
            fields=["id", "name", "default_code", "categ_id", "qty_available"],
            limit=limit,
        )
        out = []
        for r in recs:
            cat = r["categ_id"][1] if r.get("categ_id") else "Sin categoría"
            out.append({
                "id": r["id"],
                "name": r.get("name"),
                "default_code": r.get("default_code") or "",
                "categoria": cat,
                "qty": r.get("qty_available") or 0,
            })
        out.sort(key=lambda x: (x["categoria"], -x["qty"]))
        return out

    # ---- búsqueda por referencia exacta (SKU / default_code) ----
    def lookup_reference(self, code: str) -> dict | None:
        """Producto cuyo default_code coincide EXACTO con `code`, o None."""
        code = (code or "").strip()
        if not code:
            return None
        field = settings.odoo_reference_field
        recs = self.execute(
            "product.template", "search_read",
            [[field, "=", code]],
            fields=["id", "name", field], limit=1,
        )
        if not recs:
            return None
        r = recs[0]
        return {"id": r["id"], "name": r.get("name"), "default_code": r.get(field)}

    def suggest_references(self, code: str, limit: int = 8) -> list[dict]:
        """Sugerencias de referencias cuyo default_code empieza por `code`."""
        code = (code or "").strip()
        if not code:
            return []
        field = settings.odoo_reference_field
        recs = self.execute(
            "product.template", "search_read",
            [[field, "=ilike", code + "%"]],
            fields=["id", "name", field], limit=limit,
        )
        return [{"id": r["id"], "name": r.get("name"),
                 "default_code": r.get(field)} for r in recs]

    # ---- variantes de color (para asignar imágenes por color) ----
    def get_color_variants(self, code: str) -> dict | None:
        """Resuelve el producto por referencia y agrupa sus variantes por COLOR.

        Devuelve {"template": {...}, "colors": [{"color", "variant_ids":[...]}]}.
        Si el producto no tiene atributo de color, "colors" viene vacío y el
        flujo cae al nivel de plantilla (comportamiento anterior).
        """
        tmpl = self.lookup_reference(code)
        if not tmpl:
            return None
        variants = self.execute(
            "product.product", "search_read",
            [["product_tmpl_id", "=", tmpl["id"]]],
            fields=["id", "product_template_attribute_value_ids"],
        )
        val_ids = sorted({v for r in variants
                          for v in r.get("product_template_attribute_value_ids", [])})
        val_map: dict[int, dict] = {}
        if val_ids:
            for v in self.execute(
                "product.template.attribute.value", "read", val_ids,
                fields=["id", "name", "attribute_id"],
            ):
                val_map[v["id"]] = v
        wanted = (settings.odoo_color_attribute or "color").lower()
        colors: dict[str, dict] = {}
        for r in variants:
            color_name = None
            for vid in r.get("product_template_attribute_value_ids", []):
                v = val_map.get(vid)
                attr = v.get("attribute_id") if v else None
                if not (v and isinstance(attr, (list, tuple)) and len(attr) == 2):
                    continue
                attr_name = (attr[1] or "").lower()
                # Acepta "Color", "Colour", "Colores"… y el nombre configurado.
                if "colo" in attr_name or wanted in attr_name:
                    color_name = v.get("name")
                    break
            if color_name is None:
                continue   # variante sin color: no se ofrece en el selector
            colors.setdefault(color_name, {"color": color_name, "variant_ids": []})
            colors[color_name]["variant_ids"].append(r["id"])
        return {"template": tmpl,
                "colors": sorted(colors.values(), key=lambda c: c["color"])}

    def set_variant_images(self, template_id: int, variant_ids: list[int],
                           images_png: list[bytes]) -> None:
        """Asigna las imágenes a TODAS las variantes dadas (las de un color).

        - image_1920 (principal) en cada variante.
        - product.image extra (con product_variant_id) por cada variante.
        - Fija la miniatura de la PLANTILLA si está vacía (imagen por defecto).
        """
        if not images_png or not variant_ids:
            return
        principal = base64.b64encode(images_png[0]).decode()
        for vid in variant_ids:
            self.execute("product.product", "write", [vid], {"image_1920": principal})

        tmpl = self.execute("product.template", "read", [template_id],
                            fields=["image_1920"])
        if tmpl and not tmpl[0].get("image_1920"):
            self.execute("product.template", "write", [template_id],
                         {"image_1920": principal})

        extras = images_png[1:]
        if extras and not self.has_model("product.image"):
            log.warning("product.image no existe (sin website_sale): solo imagen "
                        "principal en variantes; se omiten %d extras.", len(extras))
            return
        for vid in variant_ids:
            for idx, img in enumerate(extras, start=1):
                self.execute("product.image", "create", {
                    "name": f"pose-{idx}",
                    "image_1920": base64.b64encode(img).decode(),
                    "product_tmpl_id": template_id,
                    "product_variant_id": vid,
                })

    # ---- autenticación por PIN (mismo esquema que el lanzador me.yoohoo.mx) ----
    def find_employee_by_pin(self, pin: str) -> dict | None:
        """Devuelve {id, name} del empleado cuyo PIN de checador coincide, o None.

        Usa el mismo campo que el lanzador/checador (hr.employee.yh_checador_pin).
        """
        pin = (pin or "").strip()
        if not pin:
            return None
        recs = self.execute(
            "hr.employee", "search_read",
            [[settings.odoo_pin_field, "=", pin]],
            fields=["id", "name"], limit=1,
        )
        return recs[0] if recs else None


@lru_cache
def get_odoo() -> OdooClient:
    return OdooClient()


@lru_cache
def get_auth_odoo() -> OdooClient:
    """Conexión usada para validar el PIN.

    Si hay credenciales de auth separadas (p. ej. el espejo, donde viven los
    empleados/PINs del lanzador), úsalas; si no, recae en la principal.
    """
    if settings.odoo_auth_url:
        return OdooClient(
            url=settings.odoo_auth_url,
            db=settings.odoo_auth_db,
            username=settings.odoo_auth_username,
            api_key=settings.odoo_auth_api_key,
        )
    return get_odoo()
