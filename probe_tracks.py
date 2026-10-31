"""Temporary probe: can a Bandcamp album page (the "Listen:" link in the video description) give the tracklist?"""
import html
import json
import re
import urllib.request

from lmn import http

for url in ["https://hmltd.bandcamp.com/album/fangs", "https://shabazzpalaces.bandcamp.com/album/its-a-style-sport-1"]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": http.USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as r:
            status, page = r.status, r.read().decode("utf-8", "replace")
    except Exception as ex:
        print(url, "ERROR", type(ex).__name__, str(ex)[:300])
        continue
    m = re.search(r'data-tralbum="([^"]+)"', page)
    print(url, "status", status, "bytes", len(page), "tralbum", bool(m), "challenge" if "challenge" in page.lower() else "")
    if m:
        d = json.loads(html.unescape(m.group(1)))
        cur = d.get("current") or {}
        print("  title:", cur.get("title"), "release:", cur.get("release_date"), "tracks:",
              [(t.get("title"), round(t.get("duration") or 0)) for t in d.get("trackinfo", [])])
    else:
        print("  head:", re.sub(r"\s+", " ", page[:400]))
