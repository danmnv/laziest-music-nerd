"""Temporary: dry run of lmn.yt_archive on a copy of data/, to see what it would fill before running it on main."""
import json
import os
import random
import shutil
import subprocess
from collections import Counter

shutil.copytree("data", "/tmp/d", dirs_exist_ok=True)
subprocess.run(["python", "-m", "lmn.yt_archive"], check=True, env={**os.environ, "DATA_DIR": "/tmp/d"})
before = {a["id"]: a for a in json.load(open("data/archive.json"))}
after = json.load(open("/tmp/d/archive.json"))
filled = [a for a in after if a.get("score_source") == "youtube"]
years = Counter(a["published"][:4] for a in filled)
missing_years = Counter(a["published"][:4] for a in after if a.get("score") is None and not a.get("not_good") and not a.get("classic"))
print("filled by year:", dict(sorted(years.items())))
print("still missing by year:", dict(sorted(missing_years.items())))
print("kinds:", Counter("score" if a.get("score") is not None else "not_good" if a.get("not_good") else "classic" for a in filled))
random.seed(3)
for a in random.sample(filled, min(15, len(filled))):
    print(f"   {a['published'][:10]} {a['artist_name']} - {a['album']}: {a.get('score')}{' NOT GOOD' if a.get('not_good') else ''}{' CLASSIC' if a.get('classic') else ''} https://youtu.be/{a['video_id']}")
