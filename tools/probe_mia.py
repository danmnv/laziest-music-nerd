"""Temporary probe (removed before merge): is Deezer's M.I.A. «M.I.7» the album Fantano reviewed as «Christian Album»?"""
import json, sys, urllib.request
sys.path.insert(0, ".")
from lmn import http
req = urllib.request.Request("https://api.deezer.com/album/956296681", headers={"User-Agent": http.USER_AGENT})
d = json.loads(urllib.request.urlopen(req, timeout=30).read())
print(d.get("title"), d.get("release_date"), d.get("duration"), d.get("cover_xl"))
print([(t["title"], t["duration"]) for t in d.get("tracks", {}).get("data", [])])
