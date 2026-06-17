# Parche del lanzador: mosaico "Imágenes web"

El lanzador `me.yoohoo.mx` (`/app`) es un controller HTTP de Odoo y **no es un
repo git**. Vive en el VPS en:

    /opt/odoo19/custom-addons/yoohoo_percepciones/controllers/checador.py

Este parche añade un tercer mosaico **Imágenes web** (ícono 🖼️, color `#6d28d9`)
que abre directo `https://captura.yoohoo.mx/imagenes/#pin=<PIN>` usando el mismo
handoff de PIN que las demás apps. La URL se deriva de `cfg.url_captura + /imagenes/`.

Aplicar y reiniciar Odoo:

    patch -p0 < lanzador-checador.patch.md   # o aplicar a mano
    systemctl restart yoohoo-odoo.service

```diff
--- checador.py
+++ checador.py
@@ -178,6 +178,7 @@
     <div class="apps">
       <a class="app" id="app-cp" href="__CAPTURA_HREF__"><div class="ic" style="background:#1e40af">&#128203;</div><div><div class="t">Captura de Pedidos</div><div class="d">Levanta pedidos de clientes</div></div></a>
       <a class="app" id="app-inv" href="__INVENTARIO_HREF__"><div class="ic" style="background:#854d0e">&#128230;</div><div><div class="t">Inventario</div><div class="d">Consulta y movimientos</div></div></a>
+      <a class="app" id="app-img" href="__IMAGENES_HREF__"><div class="ic" style="background:#6d28d9">&#128444;&#65039;</div><div><div class="t">Imágenes web</div><div class="d">Genera fotos de producto</div></div></a>
     </div>
     <div class="logout"><a onclick="logout()">Salir / checar otra persona</a></div>
   </div>
@@ -186,6 +187,7 @@
   var INVENTARIO = __INVENTARIO_BOOL__;
   var CAPTURA_BASE = __CAPTURA_JS__;
   var INVENTARIO_BASE = __INVENTARIO_JS__;
+  var IMAGENES_BASE = __IMAGENES_JS__;
   var pin="", dots=document.getElementById("dots"), msg=document.getElementById("msg"), go=document.getElementById("go");
   function localDate(){ try{ return new Intl.DateTimeFormat('en-CA',{timeZone:'America/Mexico_City'}).format(new Date()); }catch(e){ var d=new Date(); return d.getFullYear()+"-"+("0"+(d.getMonth()+1)).slice(-2)+"-"+("0"+d.getDate()).slice(-2); } }
   function render(){ dots.textContent="\\u25CF".repeat(pin.length); }
@@ -212,6 +214,8 @@
     var inv=document.getElementById("app-inv");
     if(!INVENTARIO){ inv.classList.add("soon"); inv.removeAttribute("href"); inv.querySelector(".d").textContent="Próximamente"; }
     else{ inv.href = INVENTARIO_BASE.split("#")[0] + "#pin=" + encodeURIComponent(s.pin); }
+    var img=document.getElementById("app-img");
+    if(img && IMAGENES_BASE){ img.href = IMAGENES_BASE.split("#")[0] + "#pin=" + encodeURIComponent(s.pin); }
   }
   function logout(){ localStorage.removeItem("yh_launcher"); location.reload(); }
   function send(lat,lng,acc){
@@ -257,12 +261,15 @@
         captura = (cfg.url_captura or 'https://captura.yoohoo.mx').strip()
         inventario = (cfg.url_inventario or '').strip()
         inv_href = inventario or '#'
+        imagenes = captura.rstrip('/') + '/imagenes/'
         html = (LAUNCHER_PAGE
                 .replace('__CAPTURA_HREF__', str(escape(captura)))
                 .replace('__INVENTARIO_HREF__', str(escape(inv_href)))
                 .replace('__CAPTURA_JS__', json.dumps(captura))
                 .replace('__INVENTARIO_JS__', json.dumps(inv_href))
-                .replace('__INVENTARIO_BOOL__', 'true' if inventario else 'false'))
+                .replace('__INVENTARIO_BOOL__', 'true' if inventario else 'false')
+                .replace('__IMAGENES_HREF__', str(escape(imagenes)))
+                .replace('__IMAGENES_JS__', json.dumps(imagenes)))
         return request.make_response(
             html, headers=[('Content-Type', 'text/html; charset=utf-8')])
 
```
