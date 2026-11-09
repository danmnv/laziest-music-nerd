"""Critic scores from a music-database table the owner was given (2026-11-03): for each archive
review, the table's critic score and the outlets' own scores with links to their reviews. A one-off import, not a scraper:
we never fetch music databases ourselves (their terms forbid scripts); the owner chose to show what the table holds.

The table was put together by someone else and sometimes found another album (M.I.A. "Maya" came back as
"maya's home - i'm you, but happier"), so a row counts only when the album it found is the one asked for.

Writes data/aoty.json: {review id: {"s": AOTY critic score out of 100, "c": [{"outlet", "score", "url"}] in
ratings.PRIORITY order, then other outlets (The Needle Drop itself left out), "tnd": Fantano's score as the table has it}}.
The site uses it where Wikipedia gave no critics, and shows AOTY's score next to Metacritic's (lmn/site.py).

Run: python -m lmn.aoty <table.json> (a list of rows with the table's columns), with DATA_DIR pointing at data/; it
writes data/aoty.json only. Fantano's score on archive reviews that have none, when the table has a whole number
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
# The table's names for outlets the site lists under Wikipedia's names (ratings.PRIORITY)
NAMES = {"Consequence of Sound": "Consequence", "A.V. Club": "The A.V. Club", "Q Magazine": "Q", "SPIN": "Spin",
         "The Telegraph": "The Daily Telegraph"}
# Outlets that score out of 5 (as in their Wikipedia rows, 2026-11-03: 90%+ of each one's scores there). The table gives
# every score out of 10, so these go back out of 5 when that is exact to one decimal: 7 -> "3.5/5", 7.6 -> "3.8/5".
STARS = {"AllMusic", "Rolling Stone", "The Guardian", "Sputnikmusic", "musicOMH", "Mojo", "Slant Magazine",
         "The Observer", "Q", "The Independent", "The Daily Telegraph", "The Times", "Kerrang!", "Record Collector",
         "Metal Hammer", "DIY", "HipHopDX"}
# Outlets that give letter grades; the table's numbers for them, as paired with Wikipedia's letters on the same reviews
LETTERS = {"The A.V. Club", "Consequence", "Entertainment Weekly"}
GRADES = {10.0: "A", 9.1: "A−", 8.3: "B+", 7.5: "B", 6.7: "B−", 5.8: "C+", 5.0: "C", 4.3: "C−", 3.3: "D+", 2.5: "D"}
# NME: out of 10 in its Wikipedia rows up to 2015 (2015 mixed), out of 5 from 2016
NME_STARS_FROM = 2016


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


def score_text(outlet, r, year=None):
    """An outlet's score as the outlet writes it, from the table's number out of 10."""
    if outlet in LETTERS and r in GRADES:
        return GRADES[r]
    stars = outlet in STARS or (outlet == "NME" and year is not None and year >= NME_STARS_FROM)
    if stars and abs(round(r / 2, 1) * 2 - r) < 1e-9:
        return f"{round(r / 2, 1):g}/5"
    return f"{r:g}/10"


def _year(s):
    m = re.match(r"(\d{4})", str(s or ""))
    return int(m.group(1)) if m else None


def entry(row):
    """{"s", "c", "tnd"} from one table row, or None when it holds nothing."""
    try:
        reviews = json.loads(row.get("critic_reviews") or "[]")
    except ValueError:
        reviews = []
    rank = {name: i for i, name in enumerate(ratings.PRIORITY)}
    year = _year(row.get("input_published_date"))
    tnd, crit, other = None, [], []
    for c in reviews:
        name, r = (c.get("publication") or "").strip(), _float(c.get("rating"))
        name = NAMES.get(name, name)
        if not name or r is None:
            continue
        if "needle drop" in name.lower():
            tnd = r
            continue
        row_ = {"outlet": name, "score": score_text(name, r, year),
                **({"url": c["url"]} if (c.get("url") or "").startswith("http") else {})}
        # the outlets the site already knows first (they link to their home page without a review link); the others
        # after them, in the table's order: an album none of the known ones reviewed still shows a couple (the owner,
        # 2026-11-08: «можно каких-то пару изданий написать пусть и не из стандартного шорлиста»)
        (crit if name in rank else other).append(row_)
    crit.sort(key=lambda c: rank[c["outlet"]])
    s = _float(row.get("critic_score"))
    if not crit and not other:
        # AOTY's critic score of an album only The Needle Drop reviewed is Fantano's own score (127 rows of the table,
        # 2026-11-08), not the critics': not shown
        s = None
    out = {"s": round(s * 10) if s is not None else None, "c": (crit + other)[:ratings.KEEP], "tnd": tnd}
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
    """Fantano's score where the archive has none and AOTY has a whole number; returns how many were filled.
    Not when the archive holds two reviews under one artist and title: the table's row (and its one Fantano score) went
    to both, and it may be the other review's score."""
    n = 0
    names = {}
    for a in archive:
        k = (loose(a.get("artist_name")), loose(a.get("album")))
        names[k] = names.get(k, 0) + 1
    for a in archive:
        t = (data.get(a["id"]) or {}).get("tnd")
        if (t is None or t != int(t) or a.get("score") is not None or a.get("not_good") or a.get("classic")
                or a.get("track") or a.get("guest") or a.get("first") or a.get("redo")
                or names[(loose(a.get("artist_name")), loose(a.get("album")))] > 1):
            continue
        a["score"], a["score_source"] = int(t), "aoty"
        n += 1
    return n


def merge(rt, e):
    """A data/ratings.json entry with the music-database table's added: each outlet Wikipedia lacks (the owner, 2026-11-03: the same
    outlets card after card), in ratings.PRIORITY order, at most ratings.KEEP; its score ("aoty", out of 100); and the
    critics' average for «спорно» from it when there is no other. Where both have an outlet, Wikipedia's row stays
    (its own format and the link it cites). rt may be None."""
    if not e:
        return rt
    rt = dict(rt or {})
    if e.get("c"):
        have = {c.get("outlet") for c in rt.get("critics") or []}
        rank = {name: i for i, name in enumerate(ratings.PRIORITY)}
        both = list(rt.get("critics") or []) + [c for c in e["c"] if c["outlet"] not in have]
        # sorted() is stable: outlets outside PRIORITY keep the table's order after the known ones
        rt["critics"] = sorted(both, key=lambda c: rank.get(c.get("outlet"), len(rank)))[:ratings.KEEP]
    if e.get("s") is not None:
        rt["aoty"] = e["s"]
        if rt.get("critic_avg10") is None:
            rt["critic_avg10"], rt["critic_avg_n"] = round(e["s"] / 10, 1), None
            rt["avg_src"] = "AOTY"
    return rt


def _sec(length):
    m = re.match(r"^(?:(\d+):)?(\d+):(\d{2})$", str(length or "").strip())
    return (int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))) if m else 0


def tracks(rows, archive):
    """{review id: [[title, seconds], ...]} from the table's tracklists, for albums Deezer doesn't have (owner, 2026-11-08:
    leroy «status update music»); the same strict match as build()."""
    by_name = {}
    for a in archive:
        by_name.setdefault((loose(a.get("artist_name")), loose(a.get("album"))), []).append(a)
    out = {}
    for row in rows:
        found = by_name.get((loose(row.get("input_artist")), loose(row.get("input_album"))))
        if not found or not same_album(row):
            continue
        try:
            tl = (json.loads(row.get("album_details") or "{}") or {}).get("tracklist") or []
        except ValueError:
            continue
        t = [[(x.get("title") or "").strip(), _sec(x.get("length"))] for x in tl if (x.get("title") or "").strip()]
        if t:
            for a in found:
                out[a["id"]] = t
    return out


def add_tracks(path):
    """python -m lmn.aoty tracks <table.json>: the table's tracklist into data/albums.json for each Deezer miss without
    one (lmn/notes.py fallback keeps it; a later Deezer hit replaces the whole entry)."""
    rows = json.loads(Path(path).read_text())
    archive = json.loads((DATA / "archive.json").read_text())
    apath = DATA / "albums.json"
    al = json.loads(apath.read_text())
    n = 0
    for i, t in tracks(rows, archive).items():
        v = al.get(i)
        if isinstance(v, dict) and "miss" in v and not v.get("t"):
            v["t"] = t
            if all(sec for _, sec in t):
                v["min"] = round(sum(sec for _, sec in t) / 60)
            n += 1
    apath.write_text("{\n" + ",\n".join(json.dumps(k) + ": " + json.dumps(al[k], ensure_ascii=False, separators=(",", ":"))
                                         for k in sorted(al)) + "\n}\n")
    print(f"aoty: tracklists for {n} albums Deezer doesn't have")


def main(path):
    rows = json.loads(Path(path).read_text())
    archive = json.loads((DATA / "archive.json").read_text())
    data = build(rows, archive)
    (DATA / "aoty.json").write_text("{\n" + ",\n".join(json.dumps(k) + ": " + json.dumps(data[k], ensure_ascii=False, separators=(",", ":"))
                                                       for k in sorted(data)) + "\n}\n")
    print(f"aoty: Fantano's score would be filled for {fill_scores([dict(a) for a in archive], data)} archive reviews")


if __name__ == "__main__":
    add_tracks(sys.argv[2]) if sys.argv[1] == "tracks" else main(sys.argv[1])
