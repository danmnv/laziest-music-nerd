"""Fantano's own words from each review video's description, for every archive review that has a video: the one-line
blurb he writes under "Listen:", and his FAV TRACKS (with Deezer track IDs, so the site can embed Deezer's official
player for them; Deezer's widget plays 30-second previews). A track Deezer doesn't have gets Apple Music's official
embed instead (30-second previews for everyone, the whole track for subscribers), found with the iTunes Search API.

Writes data/notes.json: {review id: {"video_id", "blurb", "fav": [{"t": title, "dz": Deezer track id, 0 if not on
Deezer, null or missing if not found out yet; "am": Apple Music path like "us/album/x/123?i=456", 0 if not there
either}]}}. Also data/albums.json: {review id: the album on Deezer (cover, year, minutes, tracklist; see deezer_album),
0 if Deezer has no such album}, for the site's archive pages, which otherwise know less than the bot's cards
(bot-card pages have all of it from lmn/enrich.py).
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


APPLE_SLEEP = 3.1  # the iTunes Search API allows about 20 requests a minute


def apple_track(artist, title, sleep=time.sleep):
    """Apple Music path of the track ("us/album/<name>/<album id>?i=<track id>"), 0 when Apple has no such track,
    None when the search failed (asked again next run)."""
    sleep(APPLE_SLEEP)
    try:
        d = http.get_json("https://itunes.apple.com/search?" + urllib.parse.urlencode(
            {"term": f"{artist} {title}", "entity": "song", "limit": 25, "country": "us"}))
    except Exception as e:
        print(f"  ! itunes {artist} - {title}: {e}", file=sys.stderr)
        return None
    for t in d.get("results") or []:
        url = t.get("trackViewUrl") or ""
        if norm(t.get("artistName")) == norm(artist) and norm(t.get("trackName")).startswith(norm(title)[:20]) \
                and url.startswith("https://music.apple.com/"):
            return url.split("music.apple.com/", 1)[1].split("&")[0]  # drops "&uo=4"
    return 0


def deezer_album(artist, album, sleep=time.sleep):
    """What the bot's card shows for an archive album, from Deezer: {"dz": album id, "cv": 1000×1000 cover URL, "y":
    release year, "min": minutes, "t": [[title, seconds], ...]}; 0 when Deezer has no such album, None when a request
    failed (asked again next run). Album search, unlike track search, works with the artist:"..." field."""
    def get(url):
        d = http.get_json(url)
        if d.get("error"):  # e.g. the quota (50 requests per 5 seconds)
            raise RuntimeError(d["error"])
        return d
    try:
        d = get("https://api.deezer.com/search/album?q=" + urllib.parse.quote(f'artist:"{artist}" album:"{album}"') + "&limit=10")
        hit = next((x for x in d.get("data") or [] if norm((x.get("artist") or {}).get("name")) == norm(artist)
                    and norm(x.get("title")).startswith(norm(album)[:20])), None)
        if not hit:
            return 0
        sleep(SLEEP)
        full = get(f"https://api.deezer.com/album/{int(hit['id'])}")
    except Exception as e:
        print(f"  ! deezer album {artist} - {album}: {e}", file=sys.stderr)
        return None
    tracks = [[t.get("title") or "", int(t.get("duration") or 0)] for t in (full.get("tracks") or {}).get("data") or []]
    out = {"dz": int(hit["id"]), "cv": full.get("cover_xl") or hit.get("cover_xl"), "y": (full.get("release_date") or "")[:4],
           "min": round(int(full.get("duration") or 0) / 60) or None, "t": tracks}
    return {k: v for k, v in out.items() if v}


def albums(archive, old, limit=1500, deadline=None):
    """{review id: deezer_album(...) or 0} for every archive review; at most limit lookups per run and none after
    deadline (time.monotonic()), the rest next run. Newest reviews first."""
    out, n = {}, 0
    for a in sorted(archive, key=lambda x: x.get("published") or "", reverse=True):
        if not (a.get("artist_name") and a.get("album")) or a.get("track"):
            continue
        if old.get(a["id"]) is not None:
            out[a["id"]] = old[a["id"]]
        elif n < limit and not (deadline and time.monotonic() > deadline):
            n += 1
            x = deezer_album(a["artist_name"], a["album"])
            time.sleep(SLEEP)
            if x is not None:
                out[a["id"]] = x
    print(f"albums: {sum(1 for v in out.values() if v)} found on Deezer, {sum(1 for v in out.values() if v == 0)} not; lookups {n}")
    return out


def build(uploads, archive, old, deezer_limit=1500, apple_limit=200, deadline=None):
    """Notes for every archive review with a matching video; Deezer IDs looked up at most deezer_limit times per run
    (the rest next week), Apple Music paths at most apple_limit times, and no lookup after deadline (time.monotonic()), so
    the job's time limit never cuts a run before it saves. old: the previous notes.json, kept where a lookup is not
    repeated."""
    by_key = {}
    for a in archive:
        if a.get("artist_name") and a.get("album") and not a.get("guest"):
            by_key.setdefault(norm(a["artist_name"]) + "|" + norm(a["album"]), a)
    out, lookups, apple = {}, 0, 0

    def late():
        return bool(deadline) and time.monotonic() > deadline

    for v in uploads:
        a = next((by_key.get(norm(ar) + "|" + norm(al)) for ar, al in title_keys(v["title"]) if by_key.get(norm(ar) + "|" + norm(al))), None)
        if not a:
            continue
        prev = old.get(a["id"]) or {}
        # looked up before: dz is the ID, or 0 when the track isn't on Deezer (None: the search failed, ask again)
        known = {f["t"]: f["dz"] for f in prev.get("fav", []) if f.get("dz") is not None}
        known_am = {f["t"]: f["am"] for f in prev.get("fav", []) if f.get("am") is not None}
        fav = []
        for t in parse_description(v["desc"]).get("fav_tracks", [])[:5]:
            if t in known:
                fav.append({"t": t, "dz": known[t]})
            elif lookups < deezer_limit and not late():
                lookups += 1
                fav.append({"t": t, "dz": deezer_track(a["artist_name"], t)})
                time.sleep(SLEEP)  # Deezer allows about 50 requests per 5 seconds
            else:
                fav.append({"t": t})  # next run looks it up
            f = fav[-1]
            if f.get("dz") == 0:  # not on Deezer: Apple Music's player instead
                if t in known_am:
                    f["am"] = known_am[t]
                elif apple < apple_limit and not late():
                    apple += 1
                    am = apple_track(a["artist_name"], t)
                    if am is not None:
                        f["am"] = am
        n = {"video_id": v["id"], "blurb": blurb(v["desc"]), "fav": fav}
        out[a["id"]] = {k: x for k, x in n.items() if x}
    print(f"notes: {len(out)} reviews, {sum(1 for n in out.values() if n.get('blurb'))} with a blurb, "
          f"{sum(1 for n in out.values() if n.get('fav'))} with fav tracks; Deezer lookups {lookups}, Apple lookups {apple}")
    return out
