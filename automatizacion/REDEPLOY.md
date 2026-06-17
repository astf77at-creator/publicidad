# Redespliegue desde cero — Automatización de imágenes

Cómo levantar todo el sistema en un VPS nuevo (o recuperarlo). El sistema es
**autónomo en el VPS**: no depende de GitHub ni de ninguna otra máquina en
tiempo de ejecución. GitHub solo guarda este código; lo único que **no** está en
el repo son los secretos del `.env` (ver abajo).

## Arquitectura (qué corre y dónde)

```
Navegador ──HTTPS──► nginx (captura.yoohoo.mx)
   │   me.yoohoo.mx/app (lanzador Odoo) ── mosaico "Imágenes web"
   │        └─► https://captura.yoohoo.mx/imagenes/#pin=NNNN
   ├─ /imagenes/      → estáticos en /var/www/imagenes/        (la pantalla)
   └─ /img-api/<x>    → http://127.0.0.1:8080/api/<x>          (FastAPI, systemd)
                              │
                              ├─► OpenAI gpt-image-1   (genera las poses)
                              ├─► Odoo PRODUCCIÓN yoohoo2.odoo.com (productos, imágenes, etiquetas)
                              └─► Odoo ESPEJO localhost:8069      (valida el PIN del lanzador)
```

| Pieza | Ruta en el VPS | Fuente en el repo |
|---|---|---|
| Backend FastAPI | servicio `automatizacion-imagenes.service`, corre desde `/root/publicidad/automatizacion` | `automatizacion/backend/` |
| Unit systemd | `/etc/systemd/system/automatizacion-imagenes.service` | `automatizacion/deploy/automatizacion-imagenes.service` |
| Secretos | `/root/publicidad/automatizacion/.env` | **NO en git** (plantilla abajo) |
| Pantalla (estática) | `/var/www/imagenes/` | `automatizacion/pwa-imagenes/` |
| nginx `/imagenes/` | dentro de `/etc/nginx/sites-enabled/captura.yoohoo.mx` | `automatizacion/pwa-imagenes/nginx-captura-imagenes.conf` |
| nginx `/img-api/` | dentro de `/etc/nginx/sites-enabled/captura.yoohoo.mx` | `automatizacion/integracion-inventario-pwa/nginx-captura-img-api.conf` |
| Mosaico del lanzador | `/opt/odoo19/custom-addons/yoohoo_percepciones/controllers/checador.py` (**no es git**) | parche en `automatizacion/pwa-imagenes/lanzador-checador.patch.md` |

## Requisitos previos

- Ubuntu con Python 3.12, `python3-venv`, `build-essential`, nginx, certbot.
- Odoo producción accesible (Odoo Online `yoohoo2.odoo.com`) con una **API key**.
- Odoo espejo corriendo en `localhost:8069` con el módulo `yoohoo_percepciones`
  (de ahí salen los empleados/PINs del lanzador). El mosaico vive en su
  controller `/app`.
- Dominio `captura.yoohoo.mx` apuntando al VPS, con certificado (certbot).

## Pasos

### 1. Código + dependencias del backend

```bash
git clone https://github.com/astf77at-creator/publicidad.git /root/publicidad
cd /root/publicidad/automatizacion
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Crear el `.env` (los secretos NO están en git)

Crea `/root/publicidad/automatizacion/.env` con esta plantilla y rellena las
claves reales (guarda una copia de este archivo en un gestor de secretos):

```ini
# ---- Odoo PRODUCCIÓN (productos: lookup, imágenes, etiquetas) ----
ODOO_URL=https://yoohoo2.odoo.com
ODOO_DB=yoohoo2
ODOO_USERNAME=astf77.at@gmail.com
ODOO_API_KEY=<API_KEY_DE_PRODUCCION>

ODOO_CATEGORY_FIELD=categ_id
ODOO_BRAND_FIELD=x_studio_marca_id
ODOO_REFERENCE_FIELD=default_code
ODOO_PUBLISHED_FIELD=is_published

# Etiqueta de revisión (color = índice de paleta Odoo; 2 = naranja).
# ODOO_TAG_READY vacío = no aplicar segunda etiqueta.
ODOO_TAG_REVIEW=Revisión de imágenes
ODOO_TAG_REVIEW_COLOR=2
ODOO_TAG_READY=

# ---- Auth del PIN: Odoo ESPEJO (empleados/PINs del lanzador) ----
ODOO_AUTH_URL=http://localhost:8069
ODOO_AUTH_DB=yoohoo_sandbox
ODOO_AUTH_USERNAME=admin
ODOO_AUTH_API_KEY=<API_KEY_DEL_ESPEJO>
ODOO_PIN_FIELD=yh_checador_pin

# ---- OpenAI ----
OPENAI_API_KEY=<OPENAI_API_KEY>
OPENAI_IMAGE_MODEL=gpt-image-1
POSES_POR_PRODUCTO=8

# ---- Salida de imágenes ----
IMG_ANCHO=800
IMG_ALTO=1000
IMG_MAX_KB=100

# ---- Servidor (solo loopback; NO exponer 8080) ----
HOST=127.0.0.1
PORT=8080
```

### 3. Servicio systemd (backend)

```bash
cp deploy/automatizacion-imagenes.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now automatizacion-imagenes.service
ss -tlnp | grep 127.0.0.1:8080      # debe escuchar SOLO en loopback
```

### 4. Pantalla estática

```bash
mkdir -p /var/www/imagenes
cp pwa-imagenes/index.html pwa-imagenes/app.js pwa-imagenes/styles.css \
   pwa-imagenes/manifest.webmanifest pwa-imagenes/service-worker.js /var/www/imagenes/
```

### 5. nginx (en el server HTTPS de captura.yoohoo.mx)

Inserta dentro del `server { listen 443 ssl; server_name captura.yoohoo.mx; }`
los dos bloques `location` (de `pwa-imagenes/nginx-captura-imagenes.conf` y
`integracion-inventario-pwa/nginx-captura-img-api.conf`). Luego:

```bash
nginx -t && systemctl reload nginx
```

### 6. Mosaico en el lanzador (Odoo)

Aplica el parche de `pwa-imagenes/lanzador-checador.patch.md` sobre
`/opt/odoo19/custom-addons/yoohoo_percepciones/controllers/checador.py` y
reinicia Odoo:

```bash
systemctl restart yoohoo-odoo.service   # o el nombre real del servicio Odoo
```

> El firewall NO debe abrir el 8080 (ufw deny por defecto; todo pasa por nginx).

## Verificación

```bash
# Auth + lookup (PIN de prueba en el espejo: Maria Corralco = 1707)
curl -o /dev/null -w "%{http_code}\n" https://captura.yoohoo.mx/img-api/tipos          # 401
curl -H "X-Pin: 1707" https://captura.yoohoo.mx/img-api/reference/lookup?code=RICOTTA   # 200 + JSON
curl -s https://captura.yoohoo.mx/imagenes/ | grep -o '<title>[^<]*</title>'           # Imágenes web
```

En el navegador: `https://me.yoohoo.mx/app` → checar con PIN → mosaico
**Imágenes web** → elegir Tipo, verificar una referencia, subir frente+trasero,
**Generar**.

## Dependencias en tiempo de ejecución (para que siga operando)

1. El VPS encendido.
2. Internet hacia **OpenAI** y hacia **Odoo producción** (`yoohoo2.odoo.com`).
3. El **Odoo espejo** local (`localhost:8069`) vivo: si se cae, falla el login
   por PIN aunque producción esté bien.

## Notas / gotchas

- **`.env` es lo único irrecuperable desde git.** Mantén un respaldo seguro.
- Tras actualizar Node, el backend de la Inventario PWA puede romper por
  `better-sqlite3` (ver `integracion-inventario-pwa/README.md`). No afecta a esta
  automatización, pero conviene saberlo si comparten VPS.
- Cambiar los archivos de `/var/www/imagenes/` requiere **subir el número de
  versión del service worker** (`CACHE = "imagenes-vN"`) para invalidar la caché
  del navegador.
- El backend escucha **solo en 127.0.0.1:8080**; nunca lo expongas directo.
