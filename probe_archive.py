"""Temporary: check what lmn.yt_archive would fill. (1) The text around the score it takes, for 12 random
fills. (2) Titles of 2010-2012 review videos, whose format the title parser may miss."""
import json
import random
import re

from lmn import yt_archive as ya
from lmn.tnd import tidy_entry

videos = ya.all_uploads()
by_id = {v["id"]: v for v in videos}
archive = [tidy_entry(a) for a in json.load(open("data/archive.json"))]
missing = {ya.key(a["artist_name"], a["album"]): a for a in archive
           if a.get("artist_name") and a.get("album") and a.get("score") is None and not a.get("not_good") and not a.get("classic") and not a.get("track")}
hits, old_titles, noverdict, years = [], [], [], {}
for v in videos:
    ks = [ya.key(a, b) for a, b in ya.title_keys(v["title"])]
    hit = next((k for k in ks if k in missing), None)
    if hit and ya.verdict(v["desc"]):
        hits.append(v)
        years[v["date"][:4]] = years.get(v["date"][:4], 0) + 1
    elif hit and v["date"][:4] in ("2010", "2011", "2012"):
        noverdict.append(v)
    elif v["date"][:4] in ("2010", "2011", "2012") and "review" in v["title"].lower():
        old_titles.append(v["title"])
random.seed(5)
for v in random.sample(hits, min(12, len(hits))):
    ms = list(ya.SCORE.finditer(v["desc"]))
    ctx = v["desc"][max(0, ms[-1].start() - 80): ms[-1].end() + 20].replace("\n", " | ") if ms else v["desc"][:100]
    print(f"   {v['title']!r}: {ya.verdict(v['desc'])} <- ...{ctx}...")
print(f"2010-2012 review videos not matched: {len(old_titles)}; examples:")
for t in random.sample(old_titles, min(15, len(old_titles))):
    print("   ", repr(t))
print("fills by upload year:", dict(sorted(years.items())), "total", len(hits))
print(f"2010-2012 matched but no verdict in description: {len(noverdict)}; examples:")
for v in noverdict[:6]:
    print("   ", repr(v["title"]), "<-", repr(v["desc"][-160:]))
old_hits = [v for v in hits if v["date"][:4] in ("2010", "2011", "2012")]
for v in random.sample(old_hits, min(8, len(old_hits))):
    ms = list(ya.SCORE.finditer(v["desc"]))
    ctx = v["desc"][max(0, ms[-1].start() - 80): ms[-1].end() + 20].replace("\n", " | ") if ms else v["desc"][:100]
    print(f"   OLD {v['title']!r}: {ya.verdict(v['desc'])} <- ...{ctx}...")
