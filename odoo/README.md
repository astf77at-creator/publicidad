# Conexión a Odoo (yoohoo2)

Cliente XML-RPC reutilizable para el ERP de YooHoo. Sirve para consultar
productos, precios (pricelists), inventario y ventas directamente desde la nube.

## Datos de la instancia (verificado ✅)

| Dato | Valor |
|------|-------|
| URL | `https://yoohoo2.odoo.com` |
| Base de datos | `yoohoo2` |
| Edición | Odoo SaaS Enterprise (saas~19.2+e) |
| Compañía | **YOO HOO Store** |
| Usuario | `astf77.at@gmail.com` (Administrador) |

> La instancia **presupuesto.yoohoo.mx** es un Odoo distinto (auto-hospedado para presupuestos). Esta es la principal de catálogo/ventas que sincroniza con WooCommerce.

## Cómo conectarse

La **API key NO se guarda en el repo**. Se genera en Odoo (Ajustes → Cuenta →
Claves de API/desarrollador) y se pasa por variable de entorno:

```bash
export ODOO_URL="https://yoohoo2.odoo.com"
export ODOO_DB="yoohoo2"
export ODOO_USER="astf77.at@gmail.com"
export ODOO_KEY="<tu-api-key>"

python3 odoo/odoo_client.py     # prueba la conexión e imprime un resumen
```

## Uso como librería

```python
from odoo_client import OdooClient

odoo = OdooClient.from_env()

# Pantalones wide leg más recientes y publicados
productos = odoo.search_read(
    "product.template",
    [["name", "ilike", "wide leg"], ["sale_ok", "=", True], ["is_published", "=", True]],
    ["name", "default_code", "list_price"],
    order="create_date desc",
    limit=10,
)
```

## Modelos útiles

| Modelo | Para qué |
|--------|----------|
| `product.template` | productos (plantillas) — nombre, SKU `default_code`, `list_price`, `is_published` |
| `product.product` | variantes (talla/color) |
| `product.category` | categorías |
| `product.pricelist` | listas de precios (Menudeo=15, Mayoreo=4, Corridas=3, Venta Online=8…) |
| `sale.order` | pedidos |

## Seguridad

- La clave de API **nunca** debe commitearse. Si se filtra, revócala en Odoo y genera otra.
- El usuario administrador tiene acceso total: ten cuidado con escrituras masivas en producción.
