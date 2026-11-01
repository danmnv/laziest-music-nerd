import unittest
import urllib.parse

from lmn import http, links


class Probe(unittest.TestCase):  # temporary: what Deezer's track search answers from Actions
    def test_probe(self):
        for q in ['artist:"Radiohead" track:"Karma Police"', 'artist:"radiohead" track:"karma police"', "radiohead karma police",
                  'track:"karma police"', 'artist:"Radiohead" album:"OK Computer"', "radiohead ok computer"]:
            for kind in ("track", "album"):
                try:
                    raw = http.request(f"https://api.deezer.com/search/{kind}?q={urllib.parse.quote(q)}&limit=2")
                    print("PROBE", kind, q, raw[:300])
                except Exception as e:
                    print("PROBE", kind, q, "ERR", e)
        a = links.deezer_album("Radiohead", "OK Computer")
        print("PROBE deezer_album ->", a and (a["id"], [t["title"] for t in (a.get("tracks") or [])][:4]))
        print("PROBE track 3135556", http.request("https://api.deezer.com/track/3135556")[:200])
