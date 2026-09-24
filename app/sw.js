// Сначала сеть, потом кэш: так обновления приложения приходят сразу,
// а без интернета всё равно открывается последняя версия.
const CACHE = "diary-v3";
const SHELL = ["./", "index.html", "style.css", "app.js", "manifest.webmanifest", "icon-180.png", "icon-512.png"];
const NET_TIMEOUT = 4000;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // Погоду и прочие чужие адреса не трогаем: у них свой кэш в app.js.
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const res = await Promise.race([
        fetch(e.request),
        new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), NET_TIMEOUT)),
      ]);
      if (res.ok) cache.put(e.request, res.clone());
      return res;
    } catch {
      const hit = await cache.match(e.request, { ignoreSearch: true });
      if (hit) return hit;
      throw new Error("offline");
    }
  })());
});
