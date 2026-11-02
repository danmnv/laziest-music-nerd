"""Apple Music links for the archive, found from GitHub Actions (workflow «Ссылки на Apple Music»).

The bot looks an album up on Apple's iTunes Search API when its card is opened, but Apple limits requests per IP
address, and the Worker's address is shared with other Cloudflare sites: on 2026-11-02 Apple answered it 429 "Rate
limit has been exceeded", and GNX got no Apple link (the owner). So the links are found here ahead of time and
published in the site's rt/<id>.json, which the bot's card already reads; the live search stays as the fallback.

data/apple.json: {review id: Apple Music URL or {"miss": date}}. A miss is asked again by notes.miss_due (weekly
while the review is under 60 days old, else every 90 days). The iTunes Search API allows about 20 requests a minute.
"""
import datetime
import json
import os
import time
from pathlib import Path

from . import links
from .notes import is_miss, miss_due

DATA = Path(os.environ.get("DATA_DIR", "data"))

SLEEP = 3.1  # about 20 requests a minute
PAUSE, GIVE_UP = 5, 10  # failures in a row: after PAUSE wait a minute (Apple's refusal lasts minutes); after GIVE_UP stop


def run(archive, old, limit=1000, deadline=None, today=None, sleep=time.sleep):
    """{review id: URL or {"miss": date}} for every archive album; at most limit lookups, none after deadline
    (time.monotonic()), newest reviews first. A failed request keeps the old answer and is asked again next run."""
    today = today or datetime.date.today()
    out, n, failing = {}, 0, 0
    for a in sorted(archive, key=lambda x: x.get("published") or "", reverse=True):
        if not (a.get("artist_name") and a.get("album")) or a.get("track"):
            continue
        known = old.get(a["id"])
        if known is not None and not (is_miss(known) and miss_due(known, a.get("published"), today)):
            out[a["id"]] = known
            continue
        if n >= limit or failing >= GIVE_UP or (deadline and time.monotonic() > deadline):
            if known is not None:
                out[a["id"]] = known
            continue
        if n:
            sleep(60 if failing == PAUSE else SLEEP)
        n += 1
        url = links.apple_find(a["artist_name"], a["album"])
        if url is None:  # failed (the rate limit): the old answer stays
            failing += 1
            if known is not None:
                out[a["id"]] = known
        else:
            failing = 0
            out[a["id"]] = url or {"miss": today.isoformat()}
    if failing >= GIVE_UP:
        print(f"apple: stopped after {failing} failed requests in a row (Apple refuses for now); the rest next run")
    found = sum(1 for v in out.values() if isinstance(v, str))
    print(f"apple: {found} found, {sum(1 for v in out.values() if is_miss(v))} not; lookups {n}")
    return out


def main():
    path = DATA / "apple.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    archive = json.loads((DATA / "archive.json").read_text())
    minutes = float(os.environ.get("LOOKUP_MINUTES", "50"))
    out = run(archive, old, int(os.environ.get("APPLE_LIMIT", "1000")), time.monotonic() + 60 * minutes)
    path.write_text("{\n" + ",\n".join(json.dumps(k) + ": " + json.dumps(out[k], ensure_ascii=False, separators=(",", ":"))
                                      for k in sorted(out)) + "\n}\n")


if __name__ == "__main__":
    main()
