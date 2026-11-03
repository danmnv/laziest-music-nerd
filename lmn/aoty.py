"""Critic scores from a table of albumoftheyear.org (AOTY) results the owner was given (2026-11-03): for each archive
review, AOTY's critic score and the outlets' own scores with links to their reviews. A one-off import, not a scraper:
we never fetch AOTY (its terms forbid scripts); the owner chose to show what the table holds.

The table was collected by someone else's script, which sometimes found another album (M.I.A. "Maya" came back as
"maya's home - i'm you, but happier"), so a row counts only when the album it found is the one asked for.

Writes data/aoty.json: {review id: {"s": AOTY critic score out of 100, "c": [{"outlet", "score", "url"}] in
ratings.PRIORITY order (The Needle Drop itself left out), "tnd": Fantano's score as AOTY has it}}.
The site uses it where Wikipedia gave no critics, and shows AOTY's score next to Metacritic's (lmn/site.py).

Run: python -m lmn.aoty <table.json> (a list of rows with the table's columns), with DATA_DIR pointing at data/; it
writes data/aoty.json only. Fantano's score on archive reviews that have none, when AOTY has a whole number
(score_source "aoty"), is filled by the weekly step after the specials run (lmn/notes.py apply_dates), on a fresh
archive.json: check.py writes that file twice an hour."""
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

from . import ratings

DATA = Path(os.environ.get("DATA_DIR", "data"))


def key(s):
    """A name for matching: no accents, "&" = "and", no "the"/"and"/"feat", letters and digits only."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("&", " and ")
    s = re.sub(r"\b(the|and|feat|ft|with)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def loose(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def same_album(row):
    """The album the table's script found is the one it was asked for (the artist may be credited more fully)."""
    fa, ft = key(row.get("found_artist")), key(row.get("found_title"))
    ia, ib = key(row.get("input_artist")), key(row.get("input_album"))
    return bool(ft) and ft == ib and bool(fa) and (fa == ia or ia in fa or fa in ia)


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def entry(row):
    """{"s", "c", "tnd"} from one table row, or None when it holds nothing."""
    try:
        reviews = json.loads(row.get("critic_reviews") or "[]")
    except ValueError:
        reviews = []
    rank = {name: i for i, name in enumerate(ratings.PRIORITY)}
    tnd, crit = None, []
    for c in reviews:
        name, r = (c.get("publication") or "").strip(), _float(c.get("rating"))
        if not name or r is None:
            continue
        if "needle drop" in name.lower():
            tnd = r
        elif name in rank:  # the outlets the site already knows (and links to their home page without a review link)
            crit.append({"outlet": name, "score": f"{r:g}/10", **({"url": c["url"]} if (c.get("url") or "").startswith("http") else {})})
    crit.sort(key=lambda c: rank[c["outlet"]])
    s = _float(row.get("critic_score"))
    out = {"s": round(s * 10) if s is not None else None, "c": crit[:ratings.KEEP], "tnd": tnd}
    return {k: v for k, v in out.items() if v not in (None, [])} or None


def build(rows, archive):
    """{review id: entry} for every archive review whose row matched; rows whose found album differs are skipped."""
    by_name = {}
    for a in archive:
        by_name.setdefault((loose(a.get("artist_name")), loose(a.get("album"))), []).append(a)
    out, skipped = {}, 0
    for row in rows:
        found = by_name.get((loose(row.get("input_artist")), loose(row.get("input_album"))))
        if not found:
            continue
        if not same_album(row):
            skipped += 1
            continue
        e = entry(row)
        if e:
            for a in found:
                out[a["id"]] = e
    print(f"aoty: {len(out)} reviews; {skipped} rows skipped (another album found)")
    return out


def fill_scores(archive, data):
    """Fantano's score where the archive has none and AOTY has a whole number; returns how many were filled."""
    n = 0
    for a in archive:
        t = (data.get(a["id"]) or {}).get("tnd")
        if (t is None or t != int(t) or a.get("score") is not None or a.get("not_good") or a.get("classic")
                or a.get("track") or a.get("guest")):
            continue
        a["score"], a["score_source"] = int(t), "aoty"
        n += 1
    return n


def merge(rt, e):
    """A data/ratings.json entry with AOTY's added: its outlets where Wikipedia gave none, its score ("aoty", out of
    100), and the critics' average for «спорно» from it when there is no other. rt may be None."""
    if not e:
        return rt
    rt = dict(rt or {})
    if not rt.get("critics") and e.get("c"):
        rt["critics"] = e["c"]
    if e.get("s") is not None:
        rt["aoty"] = e["s"]
        if rt.get("critic_avg10") is None:
            rt["critic_avg10"], rt["critic_avg_n"] = round(e["s"] / 10, 1), None
            rt["avg_src"] = "AOTY"
    return rt


def main(path):
    rows = json.loads(Path(path).read_text())
    archive = json.loads((DATA / "archive.json").read_text())
    data = build(rows, archive)
    (DATA / "aoty.json").write_text("{\n" + ",\n".join(json.dumps(k) + ": " + json.dumps(data[k], ensure_ascii=False, separators=(",", ":"))
                                                       for k in sorted(data)) + "\n}\n")
    print(f"aoty: Fantano's score would be filled for {fill_scores([dict(a) for a in archive], data)} archive reviews")


if __name__ == "__main__":
    main(sys.argv[1])
