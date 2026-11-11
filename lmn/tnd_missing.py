"""Reviews theneedledrop.com has but the archive doesn't.

The archive was built from the site's posts tagged "album reviews" (check.py, tnd.fetch_all_light). For some of its
past the site files reviews without that tag: everything from 11 Feb to 11 Aug 2015 ("To Pimp a Butterfly", "Currents",
"The Epic" …) sits at theneedledrop.com/2015-6-…, not under /album-reviews/. Found on 2026-11-11, when the bot
said Fantano had not reviewed "To Pimp a Butterfly".

This walks every post that lacks the tag and keeps the ones that are plainly a review: an "Artist - Album" title and
a verdict among the tags (a score, NOT GOOD, CLASSIC). The site's daily track picks and video posts have no verdict
tag, so they stay out; so does a single-song review, which can't be told from them. What the archive already has,
by post id or by artist and album, is left alone.

Run by hand: Actions → «Пропущенные обзоры с сайта». MODE=dry prints the list; MODE=run also adds the reviews to
data/archive.json (the next check then rebuilds the bot's archive.min.json and the site). SINCE / UNTIL (YYYY-MM-DD)
narrow the walk to posts published between them. About one request a second, 100 posts each.
"""
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from . import http, tnd
from .enrich import archive_entry
from .musicbrainz import norm

DATA = Path(os.environ.get("DATA_DIR", "data"))
TAG = "album-reviews"
MAX_PAGES = 600  # 60,000 posts: far more than the site has; a walk that long means the paging is broken


def key(a):
    return norm(a.get("artist_name") or "") + "|" + norm(a.get("album") or "")


def walk(since=None, until=None, sleep=time.sleep, log=print):
    """Every post without the "album reviews" tag, oldest first, without its text. If the site refuses the "not this
    tag" filter, every post is asked for and the tagged ones are dropped here."""
    dates = (f"published_at:>'{since}'" if since else "", f"published_at:<'{until}'" if until else "")
    for flt in ("+".join(x for x in (f"tag:-{TAG}", *dates) if x), "+".join(x for x in dates if x)):
        page, n = 1, 0
        try:
            while page:
                if page > MAX_PAGES:
                    raise RuntimeError(f"more than {MAX_PAGES} pages: stopped")
                d = tnd.fetch_posts(limit=100, page=page, filter=flt)
                if page == 1:
                    log(f"posts to look through: {d['meta']['pagination'].get('total')}" + ("" if TAG in flt else " (all posts: the tag filter was refused)"))
                for p in d["posts"]:
                    if not any(t.get("slug") == TAG for t in p.get("tags", [])):
                        n += 1
                        yield p
                page = d["meta"]["pagination"].get("next")
                sleep(1)
            return
        except http.HttpError as e:
            if n or TAG not in flt or e.status not in (400, 422):  # only a refused filter is tried the other way
                raise
            log(f"the site refused the filter (HTTP {e.status}); walking every post instead")


def missing(posts, archive):
    """(entries to add, counts). posts: Ghost posts with their tags; archive: data/archive.json's list."""
    ids = {a["id"] for a in archive}
    keys = {key(a) for a in archive if a.get("artist_name") and a.get("album")}
    out, n = [], Counter()
    for p in posts:
        n["posts"] += 1
        rev = tnd.parse_post(p)
        if not (rev.get("artist_name") and rev.get("album")):
            continue
        if rev["score"] is None and not rev["not_good"] and not rev["classic"]:
            continue  # no verdict tag: a track pick, a video, a news post
        n["reviews"] += 1
        if rev["id"] in ids or key(rev) in keys:
            n["known"] += 1
            continue
        ids.add(rev["id"])
        keys.add(key(rev))  # the site posted some reviews twice: the first one counts
        out.append(tnd.tidy_entry(archive_entry(rev)))
    n["new"] = len(out)
    return out, n


def badge(a):
    return "CLASSIC" if a.get("classic") else "NOT GOOD" if a.get("not_good") else f"{a['score']}/10"


def main():
    mode = os.environ.get("MODE", "dry")
    path = DATA / "archive.json"
    archive = json.loads(path.read_text())
    new, n = missing(walk(os.environ.get("SINCE") or None, os.environ.get("UNTIL") or None), archive)
    print(f"posts without the tag: {n['posts']}; reviews among them: {n['reviews']}; already in the archive: {n['known']}; missing: {n['new']}")
    by_year = Counter(a["published"][:4] for a in new)
    print("missing by year: " + ", ".join(f"{y}: {by_year[y]}" for y in sorted(by_year)))
    for a in sorted(new, key=lambda a: a["published"]):
        print(f"  {a['published'][:10]}  {badge(a):8}  {a['artist_name']} — {a['album']}")
    if mode != "run":
        print("dry run: nothing written")
        return
    if not new:
        return
    path.write_text(json.dumps(archive + new, ensure_ascii=False, indent=1) + "\n")
    print(f"archive: {len(archive)} → {len(archive) + len(new)} reviews")


if __name__ == "__main__":
    sys.exit(main())
