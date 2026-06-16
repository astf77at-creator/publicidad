# Integración "Imágenes web" en la Inventario PWA

Añade una pantalla nueva **Imágenes web** a la Inventario PWA existente
(`https://captura.yoohoo.mx/inventario/`, Vite + React 18 + react-router-dom),
en vez de exponer el backend en el puerto 8080.

El backend FastAPI de `automatizacion/` escucha **solo en `127.0.0.1:8080`** y se
publica bajo el mismo dominio/HTTPS de la PWA mediante un reverse proxy de nginx
en **`/img-api/`**. El puerto 8080 no se abre en el firewall.

```
Navegador ──HTTPS──► nginx (captura.yoohoo.mx)
                      ├─ /inventario/      → PWA estática (dist) + pantalla "Imágenes web"
                      └─ /img-api/<x>      → http://127.0.0.1:8080/api/<x>  (FastAPI)
                                                   │
                                                   └─► Odoo (espejo) + OpenAI gpt-image-1
```

## La PWA NO está en este repo

La Inventario PWA vive en el VPS en `/var/www/inventario-pwa/` y no es un repo
git. Aquí guardamos los artefactos de la integración (copia canónica de la
pantalla nueva, snippet de nginx, unit systemd y estos pasos) para versionarlos.
El despliegue real se hace en el VPS según los pasos de abajo.

## Archivos de esta carpeta

| Archivo | Destino en el VPS |
|---|---|
| `pages/ImagenesWeb.jsx` | `/var/www/inventario-pwa/client/src/pages/ImagenesWeb.jsx` (NUEVO) |
| `nginx-captura-img-api.conf` | snippet dentro de `/etc/nginx/sites-enabled/captura.yoohoo.mx` |
| `../deploy/automatizacion-imagenes.service` | `/etc/systemd/system/automatizacion-imagenes.service` |

## Cambios mínimos en la PWA existente (additivos)

No se modifica la lógica de ninguna pantalla existente. Solo dos inserciones:

**1) `client/src/App.jsx`** — importar la pantalla y registrar la ruta (dentro del
bloque de `<Routes>` que se renderiza con sesión iniciada):

```jsx
import ImagenesWeb from './pages/ImagenesWeb.jsx';
// ...
<Route path="/imagenes" element={<ImagenesWeb />} />
```

**2) `client/src/pages/Home.jsx`** — entrada de menú nueva (tras el bloque
"o buscar por modelo / nombre…"):

```jsx
<div onClick={() => nav('/imagenes')}
     style={{ padding: 16, marginTop: 12, background: 'var(--accent-bg)', color: 'var(--accent-text)',
       borderRadius: 'var(--radius-md)', textAlign: 'center', fontWeight: 500, cursor: 'pointer' }}>
  🖼️ Imágenes web
</div>
```

## Despliegue en el VPS

```bash
# 1) Pantalla nueva
scp pages/ImagenesWeb.jsx \
  root@VPS:/var/www/inventario-pwa/client/src/pages/ImagenesWeb.jsx
# + aplicar las dos inserciones de arriba en App.jsx y Home.jsx

# 2) Build de la PWA
cd /var/www/inventario-pwa/client && npm run build

# 3) Backend solo en loopback
sudo cp deploy/automatizacion-imagenes.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl restart automatizacion-imagenes
ss -tlnp | grep :8080      # debe mostrar 127.0.0.1:8080, NO 0.0.0.0

# 4) nginx: insertar el location de nginx-captura-img-api.conf en el server
#    HTTPS de captura.yoohoo.mx, validar y recargar
sudo nginx -t && sudo systemctl reload nginx

# 5) Firewall: NO abrir 8080 (ufw deny por defecto; sin regla para 8080)
```

## Prueba end-to-end (sin tocar el 8080)

```bash
curl https://captura.yoohoo.mx/img-api/tipos
curl "https://captura.yoohoo.mx/img-api/brands?category_id=130"
# El 8080 no debe responder desde fuera:
curl -m 8 http://<IP_VPS>:8080/api/health   # -> timeout / rechazado
```
En la PWA: entrar a `/inventario/`, **Home → Imágenes web**, subir frente +
espalda, elegir Tipo → Categoría → Marca → Referencia y pulsar **Generar**.

## Nota sobre tiempos (POSES_POR_PRODUCTO vs proxy_read_timeout)

El backend genera `POSES_POR_PRODUCTO` imágenes secuencialmente con gpt-image-1
(~20-40 s c/u). Con `POSES_POR_PRODUCTO=6` el job puede superar el
`proxy_read_timeout 120s` de nginx y devolver 504 al navegador (el backend sigue
y termina, pero el front no recibe la respuesta). Opciones: subir el timeout
(p. ej. 300 s) o bajar `POSES_POR_PRODUCTO`. Además, en el Odoo espejo (sin
`website_sale`) solo se guarda la imagen principal aunque se generen todas.
