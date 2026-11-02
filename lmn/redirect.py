"""The old address (danmnv.github.io/laziest-music-nerd) points to the new one (owner, 2026-11-02: no name in the
site's address). GitHub Pages can't send a server redirect, so every page of the built site is replaced with a tiny
one that moves the reader to the same page on the new address; other files (rt/*.json, wtb.json, styles) stay, so the
bot and old cached pages keep working while they switch.

Run: python -m lmn.redirect _site https://laziest-music-nerd.pages.dev"""
import html
import json
import sys
from pathlib import Path

STUB = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Laziest Music Nerd переехал</title>
<link rel="canonical" href="{url}">
<meta name="robots" content="noindex">
<meta http-equiv="refresh" content="0; url={url}">
<script>location.replace({js} + location.search + location.hash)</script>
</head><body><p>Сайт переехал: <a href="{url}">{url}</a></p></body></html>
"""

# The old address had the app's service worker (site_src/sw.js) with a cache of pages. This one replaces it once,
# empties that cache and removes itself, so phones that opened the old site don't keep a stale copy forever.
SW_GONE = """self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then((ks) => Promise.all(ks.map((k) => caches.delete(k)))).then(() => self.registration.unregister())));
"""


def target(base, rel):
    if rel == "index.html":
        rel = ""
    elif rel.endswith("/index.html"):
        rel = rel[: -len("index.html")]
    return base.rstrip("/") + "/" + rel


def run(site, base):
    n = 0
    for p in sorted(Path(site).rglob("*.html")):
        url = target(base, p.relative_to(site).as_posix())
        p.write_text(STUB.format(url=html.escape(url, quote=True), js=json.dumps(url)))
        n += 1
    (Path(site) / "sw.js").write_text(SW_GONE)
    print(f"redirect: {n} pages now lead to {base}")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
