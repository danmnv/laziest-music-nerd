"""Direct Bandcamp links for archive reviews, instead of a Bandcamp search (owner, 2026-11-01: "прямая удобнее").

1. MusicBrainz: the release's own Bandcamp album link among its URLs (often the label's page);
2. the album's address on the artist's Bandcamp (artist.bandcamp.com, from MusicBrainz) guessed from its title
   (Bandcamp makes it from the title: "Dopamine Chamber" -> /album/dopamine-chamber), kept only if that page opens
   and its own data names the same album: up to two page views per album, only to check the link;
3. otherwise the artist's own Bandcamp page: the right artist, one click from the album («Bandcamp · артист»).
Step 2 opens Bandcamp pages from a script. Bandcamp's Acceptable Use Policy forbids scraping "through the use of
scripts, robots, bots…"; the owner decided on 2026-11-02 to keep this check anyway ("мы им увеличиваем просмотры").
Not every album is on Bandcamp (most major-label records are not), so many stay without a link: the card keeps the search.

Writes data/bandcamp.json: {review id: {"u": URL or 0 (not found), "root": 1 when u is the artist's page,
"checked": ISO date}}. A miss or an artist's page is looked up again: every RECHECK_NEW_DAYS while the review is
younger than NEW_DAYS (a new album's Bandcamp page and MusicBrainz entry often come after the review), then every
RECHECK_DAYS. Fantano's own "Listen:" link (notes.json "bc") and a card's own link are used first and not looked up.
Run: python -m lmn.bandcamp (workflow «Ссылки на Bandcamp», weekly); BANDCAMP_LIMIT reviews a run."""
import html
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import http, musicbrainz
from .musicbrainz import norm

DATA = Path(os.environ.get("DATA_DIR", "data"))
RECHECK_DAYS = 90
NEW_DAYS = 60  # a review this young is looked up again every RECHECK_NEW_DAYS
RECHECK_NEW_DAYS = 7


def is_bandcamp(url):
    host = re.sub(r"^https?://", "", url or "").split("/", 1)[0].lower()
    return host == "bandcamp.com" or host.endswith(".bandcamp.com")


def slugs(title):
    """Bandcamp's address for an album title, as it makes them (a couple of ways it treats "&" and apostrophes)."""
    t = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    out = []
    for s in (t.replace("&", "and"), t):
        s = re.sub(r"['’`]", "", s)
        s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
        if s and s not in out:
            out.append(s)
    return out


def page_album(url):
    """The album title a Bandcamp album page names in its own data, or None (no such page, or not an album)."""
    try:
        text = http.request(url, retries=1)
    except http.HttpError:
        return None
    m = re.search(r'data-tralbum="([^"]+)"', text)
    if not m:
        return None
    try:
        cur = json.loads(html.unescape(m.group(1))).get("current") or {}
    except ValueError:
        return None
    return cur.get("title")


def artist_bandcamp(artist_id, cache):
    """The artist's own Bandcamp root (https://name.bandcamp.com) from MusicBrainz, or None; one request per artist."""
    if artist_id in cache:
        return cache[artist_id]
    root = None
    try:
        d = musicbrainz._get(f"artist/{artist_id}", inc="url-rels")
        for rel in d.get("relations", []):
            u = (rel.get("url") or {}).get("resource", "")
            m = re.match(r"https?://([a-z0-9-]+)\.bandcamp\.com/?$", u, re.I)
            if m and m.group(1).lower() != "www":
                root = f"https://{m.group(1).lower()}.bandcamp.com"
                break
    except http.HttpError:
        root = None
    cache[artist_id] = root
    return root


def find(artist, album, cache):
    """A Bandcamp link for this album: its album page, or the artist's own page; None when MusicBrainz has neither."""
    rg = musicbrainz.find_release_group(artist, album)
    if not rg:
        return None
    det = musicbrainz.release_details(rg.get("releases") or [])
    bc = det.get("bandcamp") or ""
    if is_bandcamp(bc) and "/album/" in bc:
        return bc.replace("http://", "https://", 1)
    root = artist_bandcamp(rg["artist_id"], cache)
    if not root:
        return None
    for s in slugs(album):
        url = f"{root}/album/{s}"
        if norm(page_album(url) or "") == norm(album):
            return url
    return root + "/"


def due(entry, now, published=""):
    """Whether to look this review up now: never looked up, or a miss / an artist's page whose wait is over."""
    if not entry:
        return True
    if entry.get("u") and not entry.get("root"):
        return False
    checked = datetime.fromisoformat(entry["checked"]).date()
    try:
        young = (checked - datetime.fromisoformat(published[:10]).date()).days < NEW_DAYS
    except ValueError:
        young = False
    return (now.date() - checked).days >= (RECHECK_NEW_DAYS if young else RECHECK_DAYS)


def save(path, store):
    lines = [json.dumps(k) + ": " + json.dumps(store[k], separators=(",", ":")) for k in sorted(store)]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("{\n" + ",\n".join(lines) + "\n}\n")
    tmp.replace(path)


def load(name, default):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else default


def run():
    limit = int(os.environ.get("BANDCAMP_LIMIT") or "500")
    deadline = time.monotonic() + 60 * float(os.environ.get("BANDCAMP_MINUTES", "45"))
    now = datetime.now(timezone.utc)
    path = DATA / "bandcamp.json"
    store = load("bandcamp.json", {})
    notes = load("notes.json", {})
    items = {r["id"]: r for name in ("archive.json", "reviews.json") for r in load(name, [])}
    todo = []
    for r in sorted(items.values(), key=lambda r: r.get("published") or "", reverse=True):
        own = (r.get("links") or {}).get("bandcamp") or ""
        if r.get("guest") or r.get("track") or not r.get("artist_name") or not r.get("album"):
            continue
        if (own and "bandcamp.com/search" not in own) or (notes.get(r["id"]) or {}).get("bc"):
            continue  # a card's own link or Fantano's "Listen:" one
        if due(store.get(r["id"]), now, r.get("published") or ""):
            todo.append(r)
    print(f"bandcamp: {len(todo)} to look up, this run up to {limit}")
    cache, done, found = {}, 0, 0
    for r in todo[:limit]:
        if time.monotonic() > deadline:
            print("bandcamp: time is up for this run")
            break
        try:
            url = find(r["artist_name"], r["album"], cache)
        except Exception as ex:  # one odd answer must not stop the batch; this review is tried next run
            print(f"  ! {r['artist_name']} — {r['album']}: {str(ex)[:80]}", file=sys.stderr)
            continue
        album_page = bool(url) and "/album/" in url
        store[r["id"]] = {"u": url or 0, **({} if album_page or not url else {"root": 1}),
                          "checked": now.date().isoformat()}
        done += 1
        found += album_page
        if done % 50 == 0:
            save(path, store)
    save(path, store)
    print(f"bandcamp: looked up {done}, album pages {found} ({round(100 * found / done) if done else 0}%); stored {len(store)}: "
          f"album pages {sum(1 for v in store.values() if v.get('u') and not v.get('root'))}, "
          f"artist pages {sum(1 for v in store.values() if v.get('root'))}")


if __name__ == "__main__":
    run()
