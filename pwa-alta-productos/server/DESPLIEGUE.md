# Despliegue del Alta de Productos en el VPS

Mini-servicio autocontenido (probado end-to-end contra yoohoo2). No toca el
backend existente de la PWA. Son 2 archivos: `alta_server.py` + `index.html`.

## 1. Copiar los archivos al VPS

En la terminal del VPS, crea la carpeta y copia ambos archivos
(`alta_server.py` e `index.html`) — por ejemplo:

```bash
mkdir -p /opt/yoohoo-alta && cd /opt/yoohoo-alta
# pega aquí alta_server.py e index.html (o clónalos del repo publicidad)
```

## 2. Probar que arranca

```bash
export ODOO_API_KEY="2a56ef14f44d77644e69ad76f76e553bb325dbf0"   # tu API key de yoohoo2
python3 alta_server.py 8090
# debe imprimir: Alta de Productos escuchando en 127.0.0.1:8090 (Odoo uid=2)
```

En otra terminal, prueba:

```bash
curl -s http://127.0.0.1:8090/api/product-attributes | head -c 200
```

## 3. Dejarlo corriendo con pm2 (como los demás servicios)

```bash
pm2 start alta_server.py --name yoohoo-alta --interpreter python3 -- 8090
pm2 env 0   # o exporta ODOO_API_KEY antes; mejor via ecosystem file:
```

Recomendado — `ecosystem.config.js` para que la key no quede en el comando:

```js
module.exports = { apps: [{
  name: "yoohoo-alta",
  script: "alta_server.py",
  interpreter: "python3",
  args: "8090",
  env: { ODOO_API_KEY: "2a56ef14f44d77644e69ad76f76e553bb325dbf0" }
}]};
```

```bash
pm2 start ecosystem.config.js && pm2 save
```

## 4. Exponerlo en nginx (bajo me.yoohoo.mx/alta)

En el server block de `me.yoohoo.mx`:

```nginx
location /alta/ {
    proxy_pass http://127.0.0.1:8090/;
    proxy_set_header Host $host;
    client_max_body_size 30m;   # fotos en base64
}
```

```bash
nginx -t && systemctl reload nginx
```

Abre en el teléfono: **https://me.yoohoo.mx/alta/**

## 5. (Opcional) Restringir acceso

El servicio no trae login propio. Opciones:
- Ponerlo detrás del mismo auth de la PWA (proteger la location en nginx con el
  mismo mecanismo de sesión/PIN), o
- `auth_basic` de nginx para dejarlo solo a Aaron / encargado de inventario.

## Notas

- Ya probado: crea el producto con 3 categorías, 4 listas de precio, variantes
  talla×color, marca, fotos e inventario inicial; y sirve tallas/colores en vivo.
- Odoo SaaS rate-limita (429): el servicio reintenta con backoff automático.
- Para actualizar: reemplaza los archivos y `pm2 restart yoohoo-alta`.
