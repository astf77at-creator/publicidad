#!/usr/bin/env python3
"""Cliente XML-RPC reutilizable para el Odoo de YooHoo (yoohoo2, SaaS Enterprise).

Conexión verificada contra la instancia `yoohoo2` (compañía "YOO HOO Store").
Las credenciales NUNCA se guardan en el código: se leen de variables de entorno.

Uso:
    export ODOO_URL="https://yoohoo2.odoo.com"
    export ODOO_DB="yoohoo2"
    export ODOO_USER="tu-correo@gmail.com"
    export ODOO_KEY="<api-key>"          # Ajustes > Cuenta > Claves de API
    python3 odoo/odoo_client.py          # imprime un resumen de conexión

    # o como librería:
    from odoo_client import OdooClient
    odoo = OdooClient.from_env()
    productos = odoo.search_read("product.template",
                                 [["sale_ok", "=", True]],
                                 ["name", "default_code", "list_price"], limit=10)
"""
from __future__ import annotations

import os
import sys
import xmlrpc.client


class OdooClient:
    def __init__(self, url: str, db: str, user: str, key: str):
        if not all([url, db, user, key]):
            raise ValueError(
                "Faltan credenciales. Define ODOO_URL, ODOO_DB, ODOO_USER y ODOO_KEY."
            )
        self.url, self.db, self.user, self.key = url.rstrip("/"), db, user, key
        self._common = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/common", allow_none=True
        )
        self._models = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/object", allow_none=True
        )
        self.uid = self._common.authenticate(self.db, self.user, self.key, {})
        if not self.uid:
            raise PermissionError(
                "Autenticación fallida: revisa ODOO_USER / ODOO_KEY / ODOO_DB."
            )

    @classmethod
    def from_env(cls) -> "OdooClient":
        return cls(
            os.environ.get("ODOO_URL", ""),
            os.environ.get("ODOO_DB", ""),
            os.environ.get("ODOO_USER", ""),
            os.environ.get("ODOO_KEY", ""),
        )

    def execute(self, model: str, method: str, *args, **kw):
        return self._models.execute_kw(
            self.db, self.uid, self.key, model, method, list(args), kw
        )

    def search_read(self, model, domain=None, fields=None, **kw):
        return self.execute(model, "search_read", domain or [], fields or [], **kw)

    def search_count(self, model, domain=None) -> int:
        return self.execute(model, "search_count", domain or [])

    def version(self) -> dict:
        return self._common.version()


def _main() -> int:
    try:
        odoo = OdooClient.from_env()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    ver = odoo.version().get("server_version", "?")
    company = odoo.search_read("res.company", [], ["name"], limit=1)
    n_prod = odoo.search_count("product.template", [["sale_ok", "=", True]])
    print("✅ Conectado a Odoo")
    print(f"   Servidor : {ver}")
    print(f"   UID      : {odoo.uid}")
    print(f"   Compañía : {company[0]['name'] if company else '?'}")
    print(f"   Productos vendibles (product.template): {n_prod}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
