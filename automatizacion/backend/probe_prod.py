"""Sonda de SOLO LECTURA contra Odoo producción. No escribe nada.

Uso (no usa .env; recibe credenciales por argumentos de entorno):
    ODOO_URL=... ODOO_DB=... ODOO_USERNAME=... ODOO_API_KEY=... \
        python -m backend.probe_prod
"""
from __future__ import annotations

import os
import xmlrpc.client

URL = os.environ["PROBE_URL"].rstrip("/")
DB = os.environ["PROBE_DB"]
USER = os.environ["PROBE_USER"]
KEY = os.environ["PROBE_KEY"]


def main() -> None:
    common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
    uid = common.authenticate(DB, USER, KEY, {})
    if not uid:
        print(f"!! NO autenticó en {URL} db={DB} user={USER}. Revisa DB/usuario/clave.")
        return
    print(f"OK autenticado en {URL}  db={DB}  uid={uid}")
    models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

    def ex(model, method, *args, **kw):
        return models.execute_kw(DB, uid, KEY, model, method, list(args), kw or {})

    # --- product.template fields ---
    pf = ex("product.template", "fields_get", [], attributes=["string", "type", "relation"])
    print("\n=== MARCA (candidatos) ===")
    for n, m in sorted(pf.items()):
        blob = (n + " " + (m.get("string") or "")).lower()
        if "marca" in blob or "brand" in blob:
            print(f"  {n:28} | {m.get('type'):9} | {m.get('relation') or ''} | {m.get('string')}")

    print("\n=== REFERENCIA / PUBLICAR ===")
    for n in ("default_code", "is_published", "website_published"):
        meta = pf.get(n)
        print(f"  {n:20} -> {'EXISTE '+meta.get('type') if meta else 'NO existe'}"
              + (f" | {meta.get('string')}" if meta else ""))

    # --- modelo product.image ---
    pi = ex("ir.model", "search_count", [["model", "=", "product.image"]])
    print(f"\n=== product.image ===\n  modelo product.image: {'EXISTE' if pi else 'NO existe'}")

    # --- etiquetas ---
    print("\n=== ETIQUETAS (product.tag) ===")
    try:
        tags = ex("product.tag", "search_read", [], fields=["id", "name"], limit=200)
        names = [t["name"] for t in tags]
        print(f"  product.tag OK. {len(tags)} etiquetas. Muestra:")
        for t in tags[:40]:
            print(f"    - {t['name']}")
        for buscar in ("Revisión de imágenes", "Listo", "WC: Faltan Datos"):
            print(f"  ¿existe '{buscar}'? -> {'SÍ' if buscar in names else 'NO (se crearía)'}")
    except Exception as e:  # noqa: BLE001
        print(f"  No se pudo leer product.tag: {e}")

    # --- campo PIN en hr.employee ---
    print("\n=== AUTH PIN (hr.employee.yh_checador_pin) ===")
    try:
        ef = ex("hr.employee", "fields_get", ["yh_checador_pin"],
                attributes=["string", "type"])
        if ef.get("yh_checador_pin"):
            print("  yh_checador_pin EXISTE en producción.")
            cnt = ex("hr.employee", "search_count",
                     [["yh_checador_pin", "!=", False]])
            print(f"  empleados con PIN configurado: {cnt}")
        else:
            print("  yh_checador_pin NO existe -> la auth por PIN NO funcionaría contra producción.")
    except Exception as e:  # noqa: BLE001
        print(f"  yh_checador_pin NO accesible: {e}")

    # --- RICOTTA ---
    print("\n=== RICOTTA ===")
    exact = ex("product.template", "search_read", [["default_code", "=", "RICOTTA"]],
               fields=["id", "name", "default_code", "is_published"], limit=5)
    print(f"  exacto default_code=RICOTTA -> {exact}")
    like = ex("product.template", "search_read", [["default_code", "ilike", "RICOTTA"]],
              fields=["id", "name", "default_code"], limit=10)
    print(f"  ilike RICOTTA -> {like}")
    byname = ex("product.template", "search_read", [["name", "ilike", "RICOTTA"]],
                fields=["id", "name", "default_code"], limit=10)
    print(f"  name ilike RICOTTA -> {byname}")


if __name__ == "__main__":
    main()
