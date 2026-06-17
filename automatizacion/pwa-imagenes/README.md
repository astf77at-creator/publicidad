# "Imágenes web" — mosaico propio en el lanzador me.yoohoo.mx

La generación de imágenes es una **app independiente** del lanzador
`me.yoohoo.mx`, junto a "Captura de Pedidos" e "Inventario". Al tocar el mosaico
**Imágenes web** se abre **directo** la pantalla de generar imágenes (sin entrar
a Inventario), identificándose con el mismo PIN del lanzador.

```
me.yoohoo.mx (lanzador Odoo /app)
  └─ mosaico "Imágenes web"  →  https://captura.yoohoo.mx/imagenes/#pin=NNNN
                                        │  (página estática)
                                        └─ fetch /img-api/* con cabecera X-Pin
                                               │
                          nginx (captura.yoohoo.mx) /img-api/ → 127.0.0.1:8080
                                               │
                                   FastAPI (automatizacion/backend)
                                        └─ Odoo (espejo) + OpenAI gpt-image-1
```

El backend FastAPI escucha **solo en `127.0.0.1:8080`** (no se abre 8080 en el
firewall); todo pasa por el dominio/HTTPS existente vía el reverse proxy
`/img-api/`.

## Autenticación (mismo esquema que el lanzador)

El lanzador pasa el PIN del empleado en el hash de la URL (`#pin=NNNN`), igual
que a las demás apps. La página lo lee y lo envía en la cabecera **`X-Pin`** en
cada llamada. El backend lo valida contra `hr.employee.yh_checador_pin`
(`require_pin` en `backend/main.py` → `find_employee_by_pin` en `backend/odoo.py`).
Sin PIN o con PIN inválido → `401` y la página muestra un aviso para entrar
desde el lanzador. `/api/health` queda abierto (sin auth) para sondeos.

## Dónde vive cada cosa

| Pieza | Ubicación |
|---|---|
| Página estática (esta carpeta) | VPS `/var/www/imagenes/` |
| Reverse proxy `/img-api/` + `location /imagenes/` | `/etc/nginx/sites-enabled/captura.yoohoo.mx` |
| Backend FastAPI (systemd, loopback) | `automatizacion/` → `automatizacion-imagenes.service` |
| **Lanzador** (mosaico) | VPS `/opt/odoo19/custom-addons/yoohoo_percepciones/controllers/checador.py` (**NO es repo git**; parche versionado en `lanzador-checador.patch.md`) |

## Despliegue en el VPS

```bash
# 1) Página independiente
ssh VPS 'mkdir -p /var/www/imagenes'
scp index.html app.js styles.css manifest.webmanifest service-worker.js \
    VPS:/var/www/imagenes/

# 2) nginx: insertar el location de nginx-captura-imagenes.conf en el server
#    HTTPS de captura.yoohoo.mx; validar y recargar
ssh VPS 'nginx -t && systemctl reload nginx'

# 3) Mosaico en el lanzador: aplicar el parche de lanzador-checador.patch.md en
#    checador.py y reiniciar Odoo
ssh VPS 'systemctl restart yoohoo-odoo.service'

# 4) Backend (loopback). Tras editar backend/*.py, sincronizar y reiniciar
ssh VPS 'systemctl restart automatizacion-imagenes.service'
ss -tlnp | grep :8080     # debe mostrar 127.0.0.1:8080, NO 0.0.0.0
```

## Prueba end-to-end

PIN de prueba en el espejo `yoohoo_sandbox`: **Maria Corralco = `1707`**.

```bash
# Auth
curl -o /dev/null -w "%{http_code}\n" https://captura.yoohoo.mx/img-api/tipos              # 401
curl -H "X-Pin: 1707" https://captura.yoohoo.mx/img-api/tipos                               # 200 + JSON
# Página
curl -s https://captura.yoohoo.mx/imagenes/ | grep -o '<title>[^<]*</title>'               # Imágenes web
```

En el navegador: entrar a **https://me.yoohoo.mx/app**, checar con un PIN válido,
y tocar el mosaico **Imágenes web** → abre la pantalla, carga el catálogo (Tipo /
Categoría / Marca / Referencia), subir frente + trasero y **Generar imágenes**.

> Nota tiempos: el backend genera `POSES_POR_PRODUCTO` imágenes secuenciales con
> gpt-image-1 (~20-40 s c/u). Con 6 poses el job puede superar `proxy_read_timeout
> 120s` de nginx y devolver 504 al navegador (el backend termina igual). En el
> espejo (sin `website_sale`) solo se guarda la imagen principal.
