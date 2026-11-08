"""Temporary probe (removed before merge): what Deezer, MusicBrainz/Cover Art Archive and iTunes answer for albums
whose cover or tracklist is missing or wrong."""
import json, sys, time, urllib.parse
sys.path.insert(0, ".")
from lmn import http, links

ALBUMS = [("KNEECAP", "FENIAN"), ("leroy", "status update music"), ("M.I.A.", "Christian Album"),
          ("Destroyer", "Kaputt"), ("Beady Eye", "Different Gear, Still Speeding"), ("Daft Punk", "Tron: Legacy Soundtrack"),
          ("Iron Maiden", "The Final Frontier"), ("HMLTD", "FANGS"), ("Women", "Public Strain")]

def g(url, **kw):
    try:
        return http.get_json(url, **kw)
    except Exception as e:
        return {"ERR": str(e)}

for artist, album in ALBUMS:
    print("=====", artist, "—", album)
    q = f"{artist} {album}"
    d = g("https://api.deezer.com/search/album?q=" + urllib.parse.quote(q) + "&limit=10")
    if d.get("error") or d.get("ERR"):
        print("deezer err", d)
    for x in (d.get("data") or [])[:6]:
        print("  dz", x["id"], repr(x["artist"]["name"]), repr(x["title"]), x.get("nb_tracks"), x.get("record_type"))
    try:
        print("  find_album ->", (links.find_album(artist, album, editions=True, sleep=lambda: time.sleep(0.3)) or {}).get("id"))
    except Exception as e:
        print("  find_album err", e)
    mb = g("https://musicbrainz.org/ws/2/release-group/?fmt=json&limit=5&query=" + urllib.parse.quote(f'releasegroup:"{album}" AND artist:"{artist}"'))
    for rg in (mb.get("release-groups") or [])[:3]:
        print("  mb", rg["id"], rg.get("score"), repr(rg.get("title")), [c.get("name") for c in rg.get("artist-credit", [])])
        try:
            r = http.get_json(f"https://coverartarchive.org/release-group/{rg['id']}")
            print("    caa", [i.get("thumbnails", {}).get("1200") or i.get("image") for i in r.get("images", []) if i.get("front")][:1])
        except Exception as e:
            print("    caa err", e)
        time.sleep(1.1)
    it = g("https://itunes.apple.com/search?" + urllib.parse.urlencode({"term": q, "entity": "album", "limit": 5}))
    for x in (it.get("results") or [])[:4]:
        print("  itunes", repr(x.get("artistName")), repr(x.get("collectionName")), x.get("artworkUrl100"))
    time.sleep(1)

for rid in ["69ffc7b4e551bc31610275bb", "6a12901ce551bc316102f66a", "69e82c12e551bc316101d90b"]:
    print("rt", rid, json.dumps(g(f"https://laziest-music-nerd.pages.dev/rt/{rid}.json"), ensure_ascii=False)[:600])
