"""Temporary probe: why Deezer missed two albums, and whether Apple Music (iTunes Search API) has them."""
import time
import urllib.parse

from lmn import http
from lmn.musicbrainz import norm


def show(label, url, pick):
    try:
        d = http.get_json(url)
    except Exception as ex:
        print(label, "ERROR", type(ex).__name__, str(ex)[:200])
        return []
    rows = d.get("data") if "data" in d else d.get("results", [])
    print(label, [pick(a) for a in rows])
    return rows


for artist, album in [("HMLTD", "FANGS"), ("Pain of Truth", "Self-Titled"), ("Pain of Truth", "Pain of Truth")]:
    for q in [f'artist:"{artist}" album:"{album}"', f"{artist} {album}"]:
        show(f"deezer [{q}]", "https://api.deezer.com/search/album?limit=10&q=" + urllib.parse.quote(q),
             lambda a: (a.get("title"), (a.get("artist") or {}).get("name"), a.get("record_type"), a.get("id")))
    rows = show(f"itunes [{artist} {album}]", "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": f"{artist} {album}", "entity": "album", "limit": 10}),
        lambda a: (a.get("collectionName"), a.get("artistName"), a.get("trackCount"), (a.get("releaseDate") or "")[:10], a.get("collectionId")))
    hit = next((a for a in rows if norm(a.get("artistName")) == norm(artist)), None)
    if hit:
        time.sleep(3)
        show(f"itunes tracks [{hit['collectionName']}]", f"https://itunes.apple.com/lookup?entity=song&id={hit['collectionId']}",
             lambda t: (t.get("trackNumber"), t.get("trackName"), round((t.get("trackTimeMillis") or 0) / 1000)) if t.get("wrapperType") == "track" else "album")
    time.sleep(3)
