"""The owner's second AOTY table (2026-11-08): albumoftheyear.org's top 5000 albums of the 2010s and of the 2020s
(10 000 rows: genres, tracklist, critic score and reviews, streaming links), collected by someone else's script. A
one-off import, not a scraper: we never fetch AOTY ourselves.

Two uses (owner, 2026-11-08: «чтобы карточки были полноценнее»):
- albums Fantano reviewed: genres up to three where the archive has one or none, Apple Music, Bandcamp and SoundCloud
  links, the critics and AOTY's score where data/aoty.json has none, a tracklist where Deezer had none (apply);
- albums he didn't review, which people open in the bot: their genres, AOTY's score and critics, tracklist and links
  (the site's u/<shard>.json, read by the Worker's unreviewedCard).

Writes data/aoty_top.json, compact (owner: «оптимизируй данные для базы»): {key: {"a": artist, "t": title, "d":
release date, "s": AOTY critic score out of 100, "g": genres, "c": [[outlet, score], ...] (4 at most), "tr": [[title,
seconds], ...], "am", "bc", "sc": album links}}. No review texts, authors, shop links or affiliate parameters.
key = key(artist, title), the same in worker/src/top.mjs.

Run: python -m lmn.aoty_top build <csv> [<csv> ...]; python -m lmn.aoty_top apply (data/ only)."""
import csv
import datetime
import json
import os
import re
import sys
import unicodedata
import urllib.parse
from pathlib import Path

from . import aoty

DATA = Path(os.environ.get("DATA_DIR", "data"))
GENRE_MAX = 22  # characters: «Festival Progressive House» and the like don't fit a card's line
GENRES = 3  # on a card (owner, 2026-11-08: «пополнить до трёх»)
CRITICS = 4


def name_key(s):
    """worker/src/follow.mjs nameKey: no accents, lower case, "&" = "and", letters and digits only."""
    s = "".join(ch for ch in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(ch))
    return "".join(ch for ch in s.lower().replace("&", "and") if ch.isalnum())


def untitled(t):
    """worker/src/releases.mjs untitled: no quotes around, no bracket at the end ("Kid A (Remastered)" -> "Kid A")."""
    t = re.sub(r'^["“]|["”]$', "", str(t or ""))
    return re.sub(r"\s*[(\[][^)\]]*[)\]]\s*$", "", t)


def key(artist, title):
    return f"{name_key(artist)[:60]}--{name_key(untitled(title))[:80]}"


def shard(k):
    """The site's file for a key: u/<shard>.json, so 10 000 albums take a few hundred files (Pages allows 20 000).
    Latin letters, digits and "-" only in a file name; the rest (30-odd albums in other scripts) share "__"."""
    s = k[:2]
    return s if re.fullmatch(r"[a-z0-9-]{2}", s) else "__"


def _date(s):
    try:
        return datetime.datetime.strptime((s or "").strip(), "%B %d, %Y").date().isoformat()
    except ValueError:
        m = re.search(r"\b(\d{4})\b", s or "")
        return m.group(1) if m else None


def _url(u, host):
    """The album's own page, without AOTY's affiliate and tracking parameters."""
    if not isinstance(u, str) or not u.startswith("http") or host not in u:
        return None
    u = u.split("?")[0]
    return u.replace("://geo.music.apple.com/", "://music.apple.com/")


def _norm_genre(g):
    return re.sub(r"[^a-z0-9]", "", g.lower())


def genres(v2):
    """AOTY's genres, primary first, as TND writes them (lower case), without long names."""
    out = []
    for g in (v2.get("genre_primary") or []) + (v2.get("genre_secondary") or []):
        g = (g or "").strip().lower()
        if g and len(g) <= GENRE_MAX and g not in out:
            out.append(g)
    return out[:5]


def add_genres(have, extra, n=GENRES):
    """have filled up to n from extra, skipping a near repeat ("pop" next to "art pop", "hip-hop" and "hip hop")."""
    out = list(have)
    for g in extra:
        if len(out) >= n:
            break
        k = _norm_genre(g)
        if k and not any(k in _norm_genre(h) or _norm_genre(h) in k for h in out):
            out.append(g)
    return out


def entry(row):
    try:
        v2 = json.loads(row.get("album_details_v2") or "{}") or {}
    except ValueError:
        v2 = {}
    try:
        links = json.loads(row.get("streaming_links_from_album") or "{}") or {}
    except ValueError:
        links = {}
    d = _date(row.get("found_release_date"))
    crit = aoty.entry({"critic_reviews": row.get("critic_reviews"), "critic_score": row.get("critic_score"),
                       "input_published_date": d}) or {}
    tr = [[(x.get("title") or "").strip(), aoty._sec(x.get("length"))] for x in v2.get("tracklist") or [] if (x.get("title") or "").strip()]
    out = {"a": (row.get("found_artist") or "").strip(), "t": (row.get("found_title") or "").strip(), "d": d,
           "s": crit.get("s"), "g": genres(v2), "c": [[c["outlet"], c["score"]] for c in crit.get("c") or []][:CRITICS],
           "tr": tr, "am": _url(links.get("apple_music"), "music.apple.com"), "bc": _url(links.get("bandcamp"), "bandcamp.com"),
           "sc": _url(links.get("soundcloud"), "soundcloud.com")}
    return {k: v for k, v in out.items() if v not in (None, [], "")}


def build(paths):
    out = {}
    for p in paths:
        with open(p, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("error") or not row.get("found_artist") or not row.get("found_title"):
                    continue
                e = entry(row)
                k = key(e["a"], e["t"])
                if k not in out or len(e) > len(out[k]):
                    out[k] = e
    return out


def reviewed(archive, top):
    """{review id: top entry} for archive reviews of an album in the table (artist and title the same)."""
    out = {}
    for a in archive:
        if a.get("track") or not a.get("artist_name") or not a.get("album"):
            continue
        e = top.get(key(a["artist_name"], a["album"]))
        if e:
            out[a["id"]] = e
    return out


def fill_genres(archive, top):
    """Up to three genres where the archive has one or none (owner, 2026-11-08); returns how many changed."""
    from . import tnd
    n = 0
    for i, e in reviewed(archive, top).items():
        a = next(x for x in archive if x["id"] == i)
        have = tnd.genres(a)
        if len(have) <= 1 and e.get("g"):
            more = add_genres(have, e["g"])
            if len(more) > len(have):
                a["genres"] = list(a.get("genres") or []) + more[len(have):]
                n += 1
    return n


def _dump(path, data):
    path.write_text("{\n" + ",\n".join(json.dumps(k) + ": " + json.dumps(data[k], ensure_ascii=False, separators=(",", ":"))
                                       for k in sorted(data)) + "\n}\n")


def apply(data_dir=DATA, today=None):
    """What the table adds to the data of reviewed albums; only empty places are filled."""
    today = (today or datetime.date.today()).isoformat()
    top = json.loads((data_dir / "aoty_top.json").read_text())
    archive = json.loads((data_dir / "archive.json").read_text())
    hits = reviewed(archive, top)
    counts = {}
    p = data_dir / "apple.json"
    apple = json.loads(p.read_text())
    counts["apple"] = 0
    for i, e in hits.items():
        if e.get("am") and not isinstance(apple.get(i), str):
            apple[i] = e["am"]
            counts["apple"] += 1
    _dump(p, apple)
    p = data_dir / "bandcamp.json"
    bc = json.loads(p.read_text())
    counts["bandcamp"] = 0
    for i, e in hits.items():
        if e.get("bc") and not (bc.get(i) or {}).get("u"):
            bc[i] = {"u": e["bc"], "checked": today}
            counts["bandcamp"] += 1
    _dump(p, bc)
    p = data_dir / "aoty.json"
    ao = json.loads(p.read_text())
    counts["aoty"] = 0
    for i, e in hits.items():
        if i not in ao and (e.get("s") is not None or e.get("c")):
            ao[i] = {k: v for k, v in {"s": e.get("s"), "c": [{"outlet": o, "score": s} for o, s in e.get("c") or []]}.items() if v not in (None, [])}
            counts["aoty"] += 1
    _dump(p, ao)
    p = data_dir / "albums.json"
    al = json.loads(p.read_text())
    counts["tracks"] = 0
    for i, e in hits.items():
        v = al.get(i)
        if e.get("tr") and (v is None or (isinstance(v, dict) and "miss" in v and not v.get("t"))):
            al[i] = {**(v or {"miss": today}), "t": e["tr"]}
            if all(s for _, s in e["tr"]):
                al[i]["min"] = round(sum(s for _, s in e["tr"]) / 60)
            counts["tracks"] += 1
    _dump(p, al)
    counts["genres"] = fill_genres(archive, top)
    if counts["genres"]:
        (data_dir / "archive.json").write_text(json.dumps(archive, ensure_ascii=False, indent=1) + "\n")
    print(f"aoty_top: {len(hits)} reviewed albums in the table; filled {counts}")
    return counts


if __name__ == "__main__":
    if sys.argv[1] == "build":
        data = build(sys.argv[2:])
        _dump(DATA / "aoty_top.json", data)
        print(f"aoty_top: {len(data)} albums")
    else:
        apply()
