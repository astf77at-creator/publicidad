// Service worker mínimo: cachea el shell para que la pantalla sea instalable.
const CACHE = "imagenes-v1";
const SHELL = ["./", "index.html", "styles.css", "app.js", "manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) =>
    Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  // No cachear llamadas al backend: siempre red.
  if (request.url.includes("/img-api/")) return;
  e.respondWith(caches.match(request).then((r) => r || fetch(request)));
});
