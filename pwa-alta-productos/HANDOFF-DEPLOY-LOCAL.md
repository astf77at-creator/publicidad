# HANDOFF — Desplegar el Alta de Productos en el VPS (para Claude Code local)

> **Para el asistente de la sesión LOCAL:** este documento tiene todo lo necesario
> para dejar vivo el "Alta de Productos" de la PWA. El motor ya está construido y
> **validado end-to-end contra el Odoo de producción** (yoohoo2). Tú solo despliegas.
> Contexto completo también en la memoria compartida (busca "alta de productos PWA").

---

## Objetivo

Dejar corriendo un mini-servicio que permite dar de alta productos desde el teléfono
(pantalla + endpoints que hablan con Odoo), accesible en **https://me.yoohoo.mx/alta/**.

## Qué es (arquitectura)

- Mini-servicio Python **autocontenido** (solo stdlib), **no toca el backend actual** de la PWA.
- 2 archivos: `alta_server.py` (servidor + motor Odoo) e `index.html` (pantalla).
- Corre en `127.0.0.1:8090`, detrás de nginx en `me.yoohoo.mx/alta/`.
- Habla con Odoo por XML-RPC (crea producto con 3 categorías, 4 listas de precio,
  variantes talla×color, marca, fotos, inventario). Trae backoff anti-429.

## Datos del entorno (verificados)

- **VPS:** `yoohoo-vps` (72.60.24.3), Ubuntu 24.04, usa **pm2** + **nginx**.
- **Odoo:** `https://yoohoo2.odoo.com`, db `yoohoo2`, user `astf77.at@gmail.com`,
  API key `2a56ef14f44d77644e69ad76f76e553bb325dbf0` (está en la máquina local:
  `credentials/yoohoo2.json`). Conexión XML-RPC verificada, uid=2.
- **Repo con los archivos:** `astf77at-creator/publicidad`, rama
  `claude/pwa-product-creation-g418vl`, carpeta `pwa-alta-productos/server/`.

---

## PASOS DE DESPLIEGUE

### 1. Obtener los archivos en el VPS

Los archivos están en el repo. Desde tu máquina (que ya tiene SSH al VPS), lo más
simple es copiarlos por scp, o clonarlos en el VPS. Opción scp desde local:

```bash
# en tu máquina local, dentro del repo publicidad (rama claude/pwa-product-creation-g418vl)
scp pwa-alta-productos/server/alta_server.py \
    pwa-alta-productos/server/index.html \
    pwa-alta-productos/server/ecosystem.config.js \
    yoohoo-vps:/opt/yoohoo-alta/
```

(Si la carpeta no existe: `ssh yoohoo-vps 'mkdir -p /opt/yoohoo-alta'` primero.)

### 2. Probar que arranca (en el VPS)

```bash
ssh yoohoo-vps
cd /opt/yoohoo-alta
export ODOO_API_KEY="2a56ef14f44d77644e69ad76f76e553bb325dbf0"
python3 alta_server.py 8090
# Debe imprimir: Alta de Productos escuchando en 127.0.0.1:8090 (Odoo uid=2)
```

En otra terminal:
```bash
curl -s http://127.0.0.1:8090/api/product-attributes | head -c 300
# debe devolver JSON con tallas_grupos y colores
```
Corta con Ctrl+C.

### 3. Dejarlo con pm2

El `ecosystem.config.js` ya trae la API key en `env`. Si prefieres no dejarla ahí,
expórtala en el entorno de pm2. Luego:

```bash
cd /opt/yoohoo-alta
pm2 start ecosystem.config.js
pm2 save
pm2 list   # confirmar que "yoohoo-alta" está "online"
```

### 4. Exponerlo en nginx (bajo me.yoohoo.mx/alta/)

En el server block de `me.yoohoo.mx` (busca el archivo en `/etc/nginx/sites-available/`),
agrega dentro del `server { ... }`:

```nginx
location /alta/ {
    proxy_pass http://127.0.0.1:8090/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    client_max_body_size 30m;   # fotos en base64
}
```

```bash
nginx -t && systemctl reload nginx
```

### 5. Verificar en el teléfono

Abre **https://me.yoohoo.mx/alta/** — debe cargar la pantalla, mostrar tallas
agrupadas (Dama 1-15, Blusas, Extras…) y 117 colores. Da de alta un producto de
prueba y confírmalo en Odoo; si es de prueba, archívalo después (`active=False`).

### 6. Restringir acceso (recomendado)

El servicio no trae login. Protégelo para que solo entren Aaron / encargado de
inventario. Opciones:
- `auth_basic` en la location de nginx, o
- integrarlo al mismo mecanismo de sesión/PIN de la PWA.

---

## Mapeo técnico (referencia, ya implementado en alta_server.py)

| Campo pantalla | Odoo | Nota |
|---|---|---|
| Nombre | `product.template.name` | obligatorio |
| Categoría | `categ_id` + `pos_categ_ids` + `public_categ_ids` | 3 IDs, se resuelven por nombre |
| SKU | `default_code` | identificador POS (no usan código de barras) |
| Marca | `x_studio_marca_id` → modelo `x_marca` (`x_name`) | se crea si no existe |
| Costo | `standard_price` | **por variante** (product.product) |
| Menudeo | `list_price` | precio base |
| Paquete/Corrida/Mayoreo | `product.pricelist.item` (listas 13/3/4) | `applied_on='1_product'` fixed |
| Impuesto | `taxes_id` | **vacío** (productos yoohoo2 sin impuesto) |
| Tipo | `type='consu'` + `is_storable=True` + `available_in_pos=True` | |
| Tallas/Colores | `attribute_line_ids` (attr 10 Tallas / 9 Colour) | genera variantes |
| Cantidad inicial | `stock.quant` + `action_apply_inventory` | |

**Gotchas ya resueltos en el código:** backoff exponencial ante 429 de Odoo SaaS;
`standard_price` por variante; `action_apply_inventory` devuelve None (se tolera);
fotos en base64 JPEG comprimido; los productos con sesión POS abierta no se borran → archivar.

## Actualizar en el futuro
Reemplaza los archivos (scp o git pull) y `pm2 restart yoohoo-alta`.

## Revocar el deploy key (cuando ya no se use)
En el VPS: quita la línea de `deploy_key` de `~/.ssh/authorized_keys`. En GitHub:
Settings → Deploy keys → borra "vps-yoohoo".
