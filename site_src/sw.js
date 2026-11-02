// Network first, cache as fallback: the app keeps opening offline with the last seen data.
// The app shell is cached on install, so the first offline start works even before a page was visited twice.
const SHELL = ["./", "index.html", "style.css", "app.js", "catalog.json", "manifest.json", "icon-192.png"];
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open("lmn").then((c) => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET" || new URL(e.request.url).origin !== location.origin) return;
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok) { const c = r.clone(); caches.open("lmn").then((x) => x.put(e.request, c)); } // never replace a good copy with an error
    return r;
  })
    .catch(() => caches.match(e.request)));
});
