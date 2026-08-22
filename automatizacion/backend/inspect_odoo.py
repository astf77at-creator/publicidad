"""Descubrimiento de la estructura de Odoo.

No conoces los nombres internos de los campos. Ejecuta esto contra el Odoo
espejo y te dice qué campos usar para MARCA, REFERENCIA, PUBLICAR y las
ETIQUETAS, para rellenar el .env.

Uso (desde la carpeta automatizacion/, con el .env apuntando al espejo):

    python -m backend.inspect_odoo
"""
from __future__ import annotations

from .odoo import get_odoo


def _print_candidates(title: str, fields: dict, predicate) -> None:
    print(f"\n=== {title} ===")
    hits = [(n, m) for n, m in fields.items() if predicate(n, m)]
    if not hits:
        print("  (ninguno obvio; mira la lista completa más abajo)")
    for name, meta in sorted(hits):
        print(f"  {name:30} | {meta.get('type'):10} | {meta.get('string')}")


def main() -> None:
    odoo = get_odoo()
    print(f"Conectado a {odoo.url} (uid={odoo.uid})")

    fields = odoo.execute("product.template", "fields_get", [],
                          attributes=["string", "type", "relation"])

    def looks_like(words):
        def f(name, meta):
            blob = (name + " " + (meta.get("string") or "")).lower()
            return any(w in blob for w in words)
        return f

    # MARCA: many2one o char que mencione marca/brand
    _print_candidates(
        "Posibles campos de MARCA",
        fields,
        lambda n, m: looks_like(["marca", "brand"])(n, m),
    )

    # REFERENCIA
    _print_candidates(
        "Posibles campos de REFERENCIA",
        fields,
        lambda n, m: n in ("default_code", "code") or looks_like(["referen", "código", "codigo", "sku"])(n, m),
    )

    # PUBLICAR: booleanos que suenen a publicar/web
    _print_candidates(
        "Posibles campos de PUBLICAR (booleanos)",
        fields,
        lambda n, m: m.get("type") == "boolean" and looks_like(["public", "publi", "web", "tienda", "shop"])(n, m),
    )

    # Todos los booleanos (por si el toggle tiene otro nombre)
    _print_candidates(
        "Todos los campos booleanos (por si el toggle de la ficha es otro)",
        fields,
        lambda n, m: m.get("type") == "boolean",
    )

    # ETIQUETAS: ¿existe product.tag y la etiqueta "Listo"?
    print("\n=== ETIQUETAS ===")
    try:
        tags = odoo.execute("product.tag", "search_read", [], fields=["id", "name"], limit=50)
        print(f"  Modelo product.tag OK. Etiquetas existentes ({len(tags)}):")
        for t in tags:
            print(f"    - {t['name']}")
    except Exception as e:  # noqa: BLE001
        print(f"  No se pudo leer product.tag: {e}")

    # CATEGORÍAS de ejemplo
    print("\n=== CATEGORÍAS (muestra) ===")
    cats = odoo.execute("product.category", "search_read", [], fields=["id", "name"], limit=10)
    for c in cats:
        print(f"  {c['id']}: {c['name']}")

    print("\nListo. Copia los nombres correctos a tu .env:")
    print("  ODOO_BRAND_FIELD, ODOO_REFERENCE_FIELD, ODOO_PUBLISHED_FIELD,")
    print("  ODOO_TAG_REVIEW, ODOO_TAG_READY")


if __name__ == "__main__":
    main()
