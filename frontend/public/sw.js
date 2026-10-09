const CACHE_NAME = "graam-gyaan-cache-v5";
const publicApi = url => /^\/api\/(catalog\/schemes|home-tiles|languages|intents|guides(?:\/[a-z_]+)?)$/.test(url.pathname);
self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    const response = await fetch("/", {cache:"reload"});
    if (!response.ok) throw new Error("App shell unavailable");
    const html = await response.clone().text();
    await cache.put("/", response);
    const assets = [...html.matchAll(/(?:src|href)="(\/assets\/[^"?]+)[^"]*"/g)].map(m => m[1]);
    await cache.addAll([...new Set(assets), "/manifest.json", "/icon-192.png", "/icon-512.png"]);
    await cache.addAll(["/api/languages", ...["hi-IN", "en-IN"].flatMap(lang => ["home-tiles", "intents", "catalog/schemes"].map(path => `/api/${path}?lang=${lang}`))]);
    const guides = ["banking", "aadhaar_pan", "ration", "family", "new_schemes", "health", "livelihood"];
    await Promise.allSettled(["hi-IN", "en-IN"].flatMap(lang => guides.map(topic => cache.add(`/api/guides/${topic}?lang=${lang}`))));
    await self.skipWaiting();
  })());
});
self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) if (name.startsWith("graam-gyaan-cache-") && name !== CACHE_NAME) await caches.delete(name);
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || event.request.method !== "GET") return;
  const shell = event.request.mode === "navigate";
  const cacheable = shell || url.pathname.startsWith("/assets/") || /^\/(icon-\d+\.png|manifest\.json)$/.test(url.pathname) || publicApi(url);
  if (!cacheable) return; // Never cache household, conversations, scans, exports or generated audio.
  event.respondWith((async () => {
    const cache = await caches.open(CACHE_NAME);
    try {
      const response = await fetch(event.request);
      if (response.ok) await cache.put(shell ? "/" : event.request, response.clone());
      return response;
    } catch {
      const cached = await cache.match(shell ? "/" : event.request);
      if (cached) {
        const headers = new Headers(cached.headers); headers.set("X-Offline-Cache", "true");
        return new Response(await cached.blob(), {status:200, headers});
      }
      return new Response(JSON.stringify({detail:"This page has not been saved for offline use."}), {status:503,headers:{"Content-Type":"application/json"}});
    }
  })());
});
