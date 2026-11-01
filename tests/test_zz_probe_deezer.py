import json
import unittest
import urllib.parse

from lmn import http, notes


class Probe(unittest.TestCase):  # temporary: what Deezer's track search answers from Actions
    def test_probe(self):
        for ar, t in [("Radiohead", "KARMA POLICE"), ("The Avalanches", "TOGETHER"), ("c*mgirl8", "KARMA POLICE")]:
            q = urllib.parse.quote(f'artist:"{ar}" track:"{t}"')
            try:
                raw = http.request(f"https://api.deezer.com/search/track?q={q}&limit=5")
                print("PROBE", ar, t, raw[:600])
            except Exception as e:
                print("PROBE", ar, t, "ERR", e)
            print("PROBE notes.deezer_track ->", notes.deezer_track(ar, t))
