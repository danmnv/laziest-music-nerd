"""Temporary: check what lmn.yt_archive would fill. (1) The text around the score it takes, for 12 random
fills. (2) Titles of 2010-2012 review videos, whose format the title parser may miss."""
import json
import random
import re

from lmn import yt_archive as ya

videos = ya.all_uploads()
by_id = {v["id"]: v for v in videos}
archive = json.load(open("data/archive.json"))
missing = {ya.key(a["artist_name"], a["album"]): a for a in archive
           if a.get("artist_name") and a.get("album") and a.get("score") is None and not a.get("not_good") and not a.get("classic")}
hits, old_titles = [], []
for v in videos:
    t = re.sub(r"\s*[-–(\[]?\s*(ALBUM|EP|MIXTAPE|TRACK)?\s*REVIEW[)\]]?\s*$", "", v["title"], flags=re.I)
    m = re.match(r"^(.+?)\s+[-–]\s+(.+)$", t)
    if m and ya.key(m.group(1), m.group(2)) in missing and ya.verdict(v["desc"]):
        hits.append(v)
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
