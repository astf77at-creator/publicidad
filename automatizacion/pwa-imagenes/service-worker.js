// Service worker: shell instalable, pero el HTML se sirve SIEMPRE desde la red
// (network-first) para no quedar atrapado en un index.html viejo cacheado.
const CACHE = "imagenes-v13";  // v13: estampa el código del producto en la imagen
const SHELL = ["./", "index.html", "styles.css", "app.js", "manifest.webmanifest"];

self.addEventListener("install", (e) => {
  self.skipWaiting();   // activar la versión nueva sin esperar a cerrar pestañas
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())   // tomar control de las páginas abiertas
  );
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  // Llamadas al backend: nunca cachear.
  if (request.url.includes("/img-api/")) return;
  // HTML / navegación: red primero; sólo cae al cache si no hay conexión.
  const accept = request.headers.get("accept") || "";
  if (request.mode === "navigate" || accept.includes("text/html")) {
    e.respondWith(
      fetch(request).catch(() =>
        caches.match(request).then((r) => r || caches.match("index.html")))
    );
    return;
  }
  // Resto de estáticos: cache primero.
  e.respondWith(caches.match(request).then((r) => r || fetch(request)));
});
