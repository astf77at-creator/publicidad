"""Cliente de Odoo vía API externa XML-RPC.

Funciona con Odoo Online (SaaS) y con el Odoo espejo del VPS sin instalar
módulos: solo usa los endpoints estándar /xmlrpc/2/common y /xmlrpc/2/object.
"""
from __future__ import annotations

import base64
import logging
import xmlrpc.client
from functools import lru_cache

from .config import settings

log = logging.getLogger(__name__)


class OdooClient:
    def __init__(self) -> None:
        self.url = settings.odoo_url.rstrip("/")
        self.db = settings.odoo_db
        self.username = settings.odoo_username
        self.api_key = settings.odoo_api_key
        self._uid: int | None = None
        self._model_exists: dict[str, bool] = {}
        self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    # ---- autenticación ----
    @property
    def uid(self) -> int:
        if self._uid is None:
            common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
            self._uid = common.authenticate(self.db, self.username, self.api_key, {})
            if not self._uid:
                raise RuntimeError("No se pudo autenticar en Odoo. Revisa credenciales.")
        return self._uid

    def execute(self, model: str, method: str, *args, **kwargs):
        return self._models.execute_kw(
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
    def _tag_id(self, name: str, create: bool = True) -> int | None:
        ids = self.execute("product.tag", "search", [["name", "=", name]], limit=1)
        if ids:
            return ids[0]
        if create:
            return self.execute("product.tag", "create", {"name": name})
        return None

    def add_tag(self, template_id: int, name: str) -> None:
        tid = self._tag_id(name)
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
