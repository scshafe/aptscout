// Service worker: opens the app with no signal and keeps the last data readable.
// Own origin, GET only. Map tiles are range requests and are not cached; the
// map area is blank offline, the lists and details still work.
const SHELL = "aptscout-shell-v1";
const DATA = "aptscout-data-v1";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(["/", "/manifest.webmanifest", "/icon.svg"])).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL && k !== DATA).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function networkFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch (err) {
    const hit = await cache.match(request);
    if (hit) return hit;
    throw err;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(SHELL);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok) cache.put(request, response.clone());
  return response;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || request.headers.has("range")) return;
  if (url.pathname.startsWith("/tiles/") || url.pathname === "/api/geocode") return;
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(networkFirst(request, DATA));
  } else if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/basemap-assets/")) {
    event.respondWith(cacheFirst(request));  // hashed build files and fonts never change under one URL
  } else if (request.mode === "navigate") {
    event.respondWith(networkFirst(new Request("/"), SHELL));
  }
});
