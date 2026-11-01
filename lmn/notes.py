"""Fantano's own words from each review video's description, for every archive review that has a video: the one-line
blurb he writes under "Listen:", and his FAV TRACKS (with Deezer track IDs, so the site can embed Deezer's official
player for them; Deezer's widget plays 30-second previews).

Writes data/notes.json: {review id: {"video_id", "blurb", "fav": [{"t": title, "dz": Deezer track id, 0 if not on
Deezer, null or missing if not found out yet}]}}.
Built by lmn/specials.py's run (same list of uploads, one YouTube pass)."""
import re
import sys
import time
import urllib.parse

from . import http
from .musicbrainz import norm
from .youtube import parse_description
from .yt_archive import title_keys

BLURB_MAX = 280
SLEEP = 0.15
NOISE = re.compile(r"^(listen|buy this|more .*reviews?|subscribe|official site|tnd |support|patreon|amazon|turntable|"
                   r"twitter|instagram|tiktok|facebook|y'all know|what do you think|what should i review|love it\?|"
                   r"fav tracks?|least fav|edited by|team:|videos edited|written by|our sponsor|thanks? |shoutouts?)", re.I)


def blurb(desc):
    """The first line of plain prose in the description: Fantano's one-sentence take, or None."""
    for line in (desc or "").split("\n"):
        line = line.strip()
        if not line or "http" in line or line.startswith("=") or NOISE.match(line):
            continue
        if line.isupper() or re.search(r"\s/\s\d{4}\s/", line):  # "ARTIST - ALBUM / 2017 / LABEL / GENRES"
            continue
        if len(line) < 25:
            continue
        if len(line) > BLURB_MAX:
            cut = line[:BLURB_MAX]
            line = cut[:cut.rfind(". ") + 1] if ". " in cut else cut.rstrip() + "…"
        return line
    return None


def deezer_track(artist, title):
    """Deezer track ID, 0 when Deezer has no such track, None when the search failed (asked again next run).
    Deezer's track search answers nothing when the query has an artist:"..." field (checked from Actions 2026-11-01:
    artist:"Radiohead" track:"Karma Police" -> 0 results), so it searches the plain words, then track:"..." alone,
    and checks the artist itself."""
    for i, q in enumerate((f"{artist} {title}", f'track:"{title}"')):
        if i:
            time.sleep(SLEEP)  # Deezer allows about 50 requests per 5 seconds
        try:
            d = http.get_json(f"https://api.deezer.com/search/track?q={urllib.parse.quote(q)}&limit=25")
        except Exception as e:
            print(f"  ! deezer {artist} - {title}: {e}", file=sys.stderr)
            return None
        if d.get("error"):  # e.g. the quota (50 requests per 5 seconds)
            print(f"  ! deezer {artist} - {title}: {d['error']}", file=sys.stderr)
            return None
        for t in d.get("data") or []:
            if norm((t.get("artist") or {}).get("name")) == norm(artist) and norm(t.get("title")).startswith(norm(title)[:20]):
                return t["id"]
    return 0


def build(uploads, archive, old, deezer_limit=1500):
    """Notes for every archive review with a matching video; Deezer IDs looked up at most deezer_limit times per run
    (the rest next week). old: the previous notes.json, kept where a lookup is not repeated."""
    by_key = {}
    for a in archive:
        if a.get("artist_name") and a.get("album") and not a.get("guest"):
            by_key.setdefault(norm(a["artist_name"]) + "|" + norm(a["album"]), a)
    out, lookups = {}, 0
    for v in uploads:
        a = next((by_key.get(norm(ar) + "|" + norm(al)) for ar, al in title_keys(v["title"]) if by_key.get(norm(ar) + "|" + norm(al))), None)
        if not a:
            continue
        prev = old.get(a["id"]) or {}
        # looked up before: dz is the ID, or 0 when the track isn't on Deezer (None: the search failed, ask again)
        known = {f["t"]: f["dz"] for f in prev.get("fav", []) if f.get("dz") is not None}
        fav = []
        for t in parse_description(v["desc"]).get("fav_tracks", [])[:5]:
            if t in known:
                fav.append({"t": t, "dz": known[t]})
            elif lookups < deezer_limit:
                lookups += 1
                fav.append({"t": t, "dz": deezer_track(a["artist_name"], t)})
                time.sleep(SLEEP)  # Deezer allows about 50 requests per 5 seconds
            else:
                fav.append({"t": t})  # next run looks it up
        n = {"video_id": v["id"], "blurb": blurb(v["desc"]), "fav": fav}
        out[a["id"]] = {k: x for k, x in n.items() if x}
    print(f"notes: {len(out)} reviews, {sum(1 for n in out.values() if n.get('blurb'))} with a blurb, "
          f"{sum(1 for n in out.values() if n.get('fav'))} with fav tracks; Deezer lookups {lookups}")
    return out
