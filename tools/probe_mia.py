"""Temporary probe (removed before merge): M.I.A.'s «Christian Album» under the name M.I.7."""
import json, sys, time, urllib.parse, urllib.request
sys.path.insert(0, ".")
from lmn import http
def raw(url):
    req = urllib.request.Request(url, headers={"User-Agent": http.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode()
    except Exception as e:
        return json.dumps({"ERR": str(e)[:200]})
for q in ["M.I.7 Christian Album", "Christian Album", "MI7 Christian Album", "M.I.7"]:
    d = json.loads(raw("https://api.deezer.com/search/album?q=" + urllib.parse.quote(q) + "&limit=10"))
    print("dz", q, [(x["id"], x["artist"]["name"], x["title"], x.get("nb_tracks"), x.get("record_type"), x.get("cover_xl")) for x in d.get("data", [])][:6], d.get("ERR"))
    time.sleep(2)
for q in ['releasegroup:"Christian Album"', 'artist:"M.I.7"', 'artist:"MI7"']:
    d = json.loads(raw("https://musicbrainz.org/ws/2/release-group/?fmt=json&limit=8&query=" + urllib.parse.quote(q)))
    print("mb", q, [(x["id"], x.get("title"), [c.get("name") for c in x.get("artist-credit", [])], x.get("first-release-date")) for x in d.get("release-groups", [])], d.get("ERR"))
    time.sleep(1.5)
d = json.loads(raw("https://itunes.apple.com/search?" + urllib.parse.urlencode({"term": "M.I.7 Christian Album", "entity": "album", "limit": 5})))
print("it", [(x.get("artistName"), x.get("collectionName"), x.get("collectionViewUrl"), x.get("artworkUrl100")) for x in d.get("results", [])])
