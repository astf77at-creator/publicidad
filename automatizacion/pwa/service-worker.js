// Service worker mínimo: cachea el shell para que la PWA sea instalable.
const CACHE = "captura-v1";
const SHELL = ["./", "index.html", "styles.css", "app.js", "manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  // No cachear llamadas a la API: siempre red.
  if (request.url.includes("/api/")) return;
  e.respondWith(caches.match(request).then((r) => r || fetch(request)));
});
