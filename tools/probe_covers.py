"""Temporary probe (removed before merge): why Deezer's search finds nothing for albums it has."""
import json, sys, time, urllib.parse, urllib.request
sys.path.insert(0, ".")
from lmn import http

def raw(url):
    req = urllib.request.Request(url, headers={"User-Agent": http.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()[:300]
    except Exception as e:
        return "ERR", str(e)[:200]

for q in ["Destroyer Kaputt", "HMLTD FANGS", "Women Public Strain", 'artist:"Destroyer" album:"Kaputt"', "Kaputt"]:
    for i in range(2):
        print(q, i, raw("https://api.deezer.com/search/album?q=" + urllib.parse.quote(q) + "&limit=5"))
        time.sleep(3)
print(raw("https://api.deezer.com/search?q=" + urllib.parse.quote("Destroyer Kaputt")))
print(raw("https://api.deezer.com/artist/2470/albums?limit=5"))
for q in ['releasegroup:"Christian Album" AND artist:"M.I.A."', 'releasegroup:"Christian Album"', 'artist:"M.I.A." AND primarytype:album']:
    print("mb", q, raw("https://musicbrainz.org/ws/2/release-group/?fmt=json&limit=5&query=" + urllib.parse.quote(q)))
    time.sleep(1.2)
