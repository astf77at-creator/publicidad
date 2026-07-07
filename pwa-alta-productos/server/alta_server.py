#!/usr/bin/env python3
"""
Mini-servicio autocontenido de Alta de Productos para YOOHOO.
Sirve la pantalla (index.html) y dos endpoints que hablan directo con Odoo:

  GET  /                     -> pantalla PWA
  GET  /api/product-attributes -> tallas (agrupadas) + colores en vivo
  POST /api/products         -> crea el producto en Odoo

No necesita tocar el backend existente. Correr en el VPS:

  export ODOO_API_KEY="<tu api key de yoohoo2>"
  python3 alta_server.py 8090          # escucha en 127.0.0.1:8090

Luego una location en nginx (ej. me.yoohoo.mx/alta -> 127.0.0.1:8090).

Sin dependencias externas (solo stdlib).
"""
import os, sys, json, xmlrpc.client, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

URL = os.environ.get("ODOO_URL", "https://yoohoo2.odoo.com")
DB = os.environ.get("ODOO_DB", "yoohoo2")
USER = os.environ.get("ODOO_USER", "astf77.at@gmail.com")
KEY = os.environ.get("ODOO_API_KEY")
if not KEY:
    sys.exit("Falta ODOO_API_KEY en el entorno")

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- Odoo XML-RPC con backoff anti-429 ----
_common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
_uid = _common.authenticate(DB, USER, KEY, {})
_models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

def c(model, method, *args, **kw):
    delay = 2
    for i in range(5):
        try:
            return _models.execute_kw(DB, _uid, KEY, model, method, list(args), kw)
        except xmlrpc.client.ProtocolError as e:
            if e.errcode == 429 and i < 4:
                time.sleep(delay); delay *= 2; continue
            raise

# ---- Motor de creación (mismo validado) ----
ATTR_TALLA, ATTR_COLOR = 10, 9
PRICELIST = {"paquete": 13, "corrida": 3, "mayoreo": 4, "menudeo": 15}

def _vals_attr(attr_id, nombres):
    ids = []
    for n in nombres:
        v = c("product.attribute.value", "search", [["attribute_id","=",attr_id],["name","=",n]], limit=1)
        ids.append(v[0] if v else c("product.attribute.value","create",{"attribute_id":attr_id,"name":n}))
    return ids

def crear_producto(spec):
    cat = c("product.category","search",[["name","=",spec["categoria"]]],limit=1)
    categ_id = cat[0] if cat else c("product.category","create",{"name":spec["categoria"]})
    pos = c("pos.category","search",[["name","=",spec["categoria"]]],limit=1)
    pub = c("product.public.category","search",[["name","=",spec["categoria"]]],limit=1)
    pos_ids = pos or [c("pos.category","create",{"name":spec["categoria"]})]
    pub_ids = pub or [c("product.public.category","create",{"name":spec["categoria"]})]
    marca_id = False
    if spec.get("marca"):
        m = c("x_marca","search",[["x_name","=",spec["marca"]]],limit=1)
        marca_id = m[0] if m else c("x_marca","create",{"x_name":spec["marca"]})

    lines = []
    if spec.get("tallas"):
        lines.append((0,0,{"attribute_id":ATTR_TALLA,"value_ids":[(6,0,_vals_attr(ATTR_TALLA,spec["tallas"]))]}))
    if spec.get("colores"):
        lines.append((0,0,{"attribute_id":ATTR_COLOR,"value_ids":[(6,0,_vals_attr(ATTR_COLOR,spec["colores"]))]}))

    vals = {
        "name": spec["nombre"], "categ_id": categ_id,
        "pos_categ_ids":[(6,0,pos_ids)], "public_categ_ids":[(6,0,pub_ids)],
        "default_code": spec.get("sku") or False,
        "list_price": spec["precios"]["menudeo"], "taxes_id":[(6,0,[])],
        "type":"consu", "is_storable":True, "available_in_pos": spec.get("pos",True) is not False,
        "attribute_line_ids": lines,
    }
    if marca_id: vals["x_studio_marca_id"] = marca_id
    if spec.get("foto_delantera"): vals["image_1920"] = spec["foto_delantera"]
    tid = c("product.template","create",vals)

    for lista in ("paquete","corrida","mayoreo"):
        p = spec["precios"].get(lista)
        if p:
            c("product.pricelist.item","create",{"pricelist_id":PRICELIST[lista],"applied_on":"1_product",
              "product_tmpl_id":tid,"compute_price":"fixed","fixed_price":p,"min_quantity":0})
    for img in spec.get("galeria") or []:
        c("product.image","create",{"product_tmpl_id":tid,"name":img["name"],"image_1920":img["data"]})

    variants = c("product.product","search",[["product_tmpl_id","=",tid]])
    if spec.get("costo"):
        c("product.product","write",variants,{"standard_price":spec["costo"]})
    if spec.get("cantidad_inicial") and spec.get("location_id"):
        qs = [c("stock.quant","create",{"product_id":v,"location_id":spec["location_id"],
                "inventory_quantity":spec["cantidad_inicial"]}) for v in variants]
        try: c("stock.quant","action_apply_inventory",qs)
        except xmlrpc.client.Fault as e:
            if "marshal None" not in str(e): raise
    return {"template_id":tid,"variant_ids":variants,"marca_id":marca_id}

# ---- Atributos (tallas agrupadas + colores) ----
ORDEN_LETRAS = ["XS","XS/S","S","S/M","M","M/L","L","L/XL","XL","XXL","XXXL"]
def _key(t):
    s=str(t).upper().strip()
    import re
    x=re.match(r"^([1-4])X$",s)
    if x: return (1,100+int(x.group(1)),"")
    if s in ORDEN_LETRAS: return (0,ORDEN_LETRAS.index(s),"")
    try: return (1,float("0" if s=="CERO" else s),s)
    except: return (2,0,s.lower())
def _grupo(t):
    import re
    s=str(t).strip()
    if re.search(r"unitalla|única",s,re.I): return "Unitalla"
    if re.match(r"^[1-4]X$",s,re.I): return "Extras"
    try: n=float("0" if re.match(r"^cero$",s,re.I) else s)
    except: return "Blusas (letras)"
    if n>=28: return "Pants 28-40"
    if n%2==1 and n<=15: return "Dama 1-15"
    if n>=16 or n%2==1: return "Extras"
    return "Pares 0-14"
ORDEN_G=["Dama 1-15","Blusas (letras)","Extras","Pants 28-40","Pares 0-14","Unitalla"]

def atributos():
    import functools
    tallas=c("product.attribute.value","search_read",[["attribute_id","=",10]],fields=["name"],order="sequence,id")
    colores=c("product.attribute.value","search_read",[["attribute_id","=",9]],fields=["name","html_color"],order="sequence,id")
    grupos={}
    for t in {x["name"].strip() for x in tallas}:
        grupos.setdefault(_grupo(t),[]).append(t)
    for g in grupos: grupos[g].sort(key=functools.cmp_to_key(lambda a,b:(_key(a)>_key(b))-(_key(a)<_key(b))))
    return {
        "tallas_grupos":[{"grupo":g,"tallas":grupos[g]} for g in ORDEN_G if g in grupos],
        "colores":[{"nombre":x["name"],"hex":x.get("html_color") or None} for x in colores],
    }

# ---- HTTP ----
class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body,bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/","/index.html"):
            try:
                html=open(os.path.join(HERE,"index.html"),"rb").read()
                self._send(200, html, "text/html; charset=utf-8")
            except FileNotFoundError:
                self._send(404, {"error":"index.html no encontrado"})
        elif self.path.startswith("/api/product-attributes"):
            try: self._send(200, atributos())
            except Exception as e: self._send(500, {"error":str(e)})
        else:
            self._send(404, {"error":"no encontrado"})

    def do_POST(self):
        if self.path.rstrip("/") == "/api/products":
            n=int(self.headers.get("Content-Length",0))
            try: spec=json.loads(self.rfile.read(n) or b"{}")
            except Exception: return self._send(400,{"error":"JSON inválido"})
            faltan=[k for k in ("nombre","categoria") if not spec.get(k)]
            if spec.get("costo") is None: faltan.append("costo")
            for l in ("paquete","corrida","mayoreo","menudeo"):
                if not spec.get("precios",{}).get(l): faltan.append(f"precio {l}")
            if faltan: return self._send(400,{"error":"Faltan campos","faltan":faltan})
            try: self._send(200, {"ok":True, **crear_producto(spec)})
            except Exception as e: self._send(500, {"ok":False,"error":str(e)})
        else:
            self._send(404, {"error":"no encontrado"})

    def log_message(self, *a): pass  # silencioso

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv)>1 else 8090
    print(f"Alta de Productos escuchando en 127.0.0.1:{port} (Odoo uid={_uid})")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
