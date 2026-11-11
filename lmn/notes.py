"""Fantano's own words from each review video's description, for every archive review that has a video: the one-line
blurb he writes under "Listen:", and his FAV TRACKS (with Deezer track IDs, so the site can embed Deezer's official
player for them; Deezer's widget plays 30-second previews). A track Deezer doesn't have gets Apple Music's official
embed instead (30-second previews for everyone, the whole track for subscribers), found with the iTunes Search API.

Writes data/notes.json: {review id: {"video_id", "blurb", "bc": Fantano's "Listen:" link when it is Bandcamp, "fav": [{"t": title, "dz": Deezer track id, 0 if not on
Deezer, null or missing if not found out yet; "am": Apple Music path like "us/album/x/123?i=456", 0 if not there
either}]}}. Also data/albums.json: {review id: the album on Deezer (cover, year, minutes, tracklist; see deezer_album),
0 if Deezer has no such album}, for the site's archive pages, which otherwise know less than the bot's cards
(bot-card pages have all of it from lmn/enrich.py).
Built by lmn/specials.py's run (same list of uploads, one YouTube pass)."""
import datetime
import re
import sys
import time
import urllib.parse

from . import http, links, musicbrainz
from .musicbrainz import norm
from .youtube import parse_description
from .yt_archive import title_keys

BLURB_MAX = 280
SLEEP = 0.15
NOISE = re.compile(r"^(listen|buy this|more .*reviews?|subscribe|official site|tnd |support|patreon|amazon|turntable|"
                   r"twitter|instagram|tiktok|facebook|y'all know|what do you think|what should i review|love it\?|"
                   r"fav tracks?|least fav|edited by|team:|videos edited|written by|our sponsor|thanks? |shoutouts?)", re.I)


def bandcamp(desc):
    """The "Listen:" link of the description when it is a Bandcamp page (the album's, sometimes the artist's), or None."""
    url = re.sub(r"^http://", "https://", parse_description(desc).get("listen_url") or "")  # old descriptions: http, Bandcamp serves https
    host = re.sub(r"^https?://", "", url).split("/", 1)[0].lower()
    return url if url.startswith("http") and (host == "bandcamp.com" or host.endswith(".bandcamp.com")) and "/search" not in url else None


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


def deezer_album(artist, album, sleep=time.sleep, named=None):
    """What the bot's card shows for an archive album, from Deezer: {"dz": album id, "cv": 1000×1000 cover URL, "y":
    release year, "min": minutes, "t": [[title, seconds], ...]}; 0 when Deezer has no such album, None when a request
    failed (asked again next run). The search: links.find_album."""
    def get(url):
        d = http.get_json(url)
        if d.get("error"):  # e.g. the quota (50 requests per 5 seconds)
            raise RuntimeError(d["error"])
        return d
    try:
        hit = links.find_album(artist, album, get, editions=True, sleep=lambda: sleep(SLEEP))
        if not hit:
            return 0
        sleep(SLEEP)
        full = get(f"https://api.deezer.com/album/{int(hit['id'])}")
        data = (full.get("tracks") or {}).get("data") or []
        if full.get("nb_tracks") and len(data) < full["nb_tracks"]:  # a long album's embedded list may be cut
            sleep(SLEEP)
            data = get(f"https://api.deezer.com/album/{int(hit['id'])}/tracks?limit=500").get("data") or data
    except Exception as e:
        print(f"  ! deezer album {artist} - {album}: {e}", file=sys.stderr)
        return None
    tracks = [[t.get("title") or "", int(t.get("duration") or 0)] for t in data]
    if not links.fits(named, tracks):  # a single under the album's title (links.fits): a miss, the fallback looks further
        print(f"  deezer album {artist} - {album}: {hit['id']} has {len(tracks)} tracks without Fantano's favourites: not the album")
        return 0
    out = {"dz": int(hit["id"]), "cv": full.get("cover_xl") or hit.get("cover_xl"), "y": (full.get("release_date") or "")[:4],
           "min": round(int(full.get("duration") or 0) / 60) or None, "t": tracks}
    return {k: v for k, v in out.items() if v}


FALLBACK = ("cv", "t", "min", "y", "mb")  # what a Deezer miss may still carry (fallback)


def fallback(artist, album, known=None, named=None, apple=None):
    """For an album Deezer doesn't have (owner, 2026-11-08: leroy «status update music», no cover in the bot): its
    MusicBrainz release group, the front cover from the Cover Art Archive and, when no tracklist is known yet (the AOTY
    table's, lmn/aoty.py tracks), MusicBrainz's. What was found before is kept. {"fb": 1} marks that it was asked."""
    # what an earlier miss found is kept; a Deezer hit found wrong (links.fits) keeps nothing
    keep = {k: known[k] for k in FALLBACK if isinstance(known, dict) and is_miss(known) and known.get(k)}
    if keep.get("cv") and keep.get("t"):
        return {**keep, "fb": 1}
    # the album on Apple Music (data/apple.json): its tracklist and cover, exact by the page's id (links.apple_tracks)
    am = links.apple_tracks(apple) if apple else None
    if am and links.fits(named, am.get("tracks")):
        if am.get("tracks") and not keep.get("t"):
            keep["t"] = [[t["title"], t["sec"] or 0] for t in am["tracks"]]
            if all(t["sec"] for t in am["tracks"]):
                keep["min"] = round(sum(t["sec"] for t in am["tracks"]) / 60)
        if am.get("cover") and not keep.get("cv"):
            keep["cv"] = am["cover"]
        if keep.get("cv") and keep.get("t"):
            return {**keep, "fb": 1}
    rg = musicbrainz.find_release_group(artist, album)
    if not rg:
        return {**keep, "fb": 1}
    keep["mb"] = rg["rg_id"]
    if rg.get("date") and not keep.get("y"):
        keep["y"] = rg["date"][:4]
    if not keep.get("cv"):
        try:
            imgs = http.get_json(f"https://coverartarchive.org/release-group/{rg['rg_id']}").get("images") or []
            front = next((i for i in imgs if i.get("front")), None)
            if front:
                th = front.get("thumbnails") or {}
                keep["cv"] = (th.get("1200") or th.get("large") or front.get("image") or "").replace("http://", "https://") or None
        except Exception as e:  # 404: no art for it; 503: the archive is busy, asked again at the next miss
            print(f"  ! cover art {artist} - {album}: {e}", file=sys.stderr)
    if not keep.get("t"):
        d = musicbrainz.release_details(rg.get("releases") or [])
        if d.get("tracks") and links.fits(named, d["tracks"]):
            keep["t"] = [[t["title"] or "", t["sec"] or 0] for t in d["tracks"]]
            keep["min"] = d.get("duration_min")
    return {**{k: v for k, v in keep.items() if v}, "fb": 1}


def found(v):
    """The album from data/albums.json, or None for a miss (0 or {"miss": date}; a miss with a cover or a tracklist from
    fallback counts as found where it is shown, see lmn/site.py deezer_found)."""
    return v if isinstance(v, dict) and v.get("dz") else None


def is_miss(v):
    return v == 0 or (isinstance(v, dict) and "miss" in v)


def miss_due(known, published, today):
    """Whether a miss is asked again: a 0 from before 2026-11-02 once (the search changed, links.find_album); then
    {"miss": date} weekly while the review is under 60 days old (Deezer often adds an album late), else every 90 days
    (as data/bandcamp.json)."""
    if known == 0:
        return True
    try:
        days = (today - datetime.date.fromisoformat(known["miss"])).days
        age = (today - datetime.date.fromisoformat(str(published or "")[:10])).days
    except (KeyError, TypeError, ValueError):
        return True
    return days >= (7 if age < 60 else 90)


def favourites(nts, i):
    """The tracks Fantano named for review i, from data/notes.json (links.fits)."""
    return [f["t"] for f in ((nts or {}).get(i) or {}).get("fav") or [] if isinstance(f, dict) and f.get("t")]


def albums(archive, old, limit=1500, deadline=None, today=None, nts=None, apple=None):
    """{review id: deezer_album(...) or {"miss": date}} for every archive review; at most limit lookups per run and
    none after deadline (time.monotonic()), the rest next run. Newest reviews first. A miss is asked again when
    miss_due; until then, and when a request fails, the old answer stays."""
    today = today or datetime.date.today()
    out, n = {}, 0
    for a in sorted(archive, key=lambda x: x.get("published") or "", reverse=True):
        if not (a.get("artist_name") and a.get("album")) or a.get("track"):
            continue
        known = old.get(a["id"])
        # a miss from before the fallback (2026-11-08) is asked once more, now with it
        due = is_miss(known) and (miss_due(known, a.get("published"), today) or (isinstance(known, dict) and not known.get("fb")))
        if known is not None and not due:
            out[a["id"]] = known
        elif n < limit and not (deadline and time.monotonic() > deadline):
            n += 1
            named = favourites(nts, a["id"])
            page = (apple or {}).get(a["id"])  # data/apple.json: the URL, or a miss
            page = page if isinstance(page, str) else None
            x = deezer_album(a["artist_name"], a["album"], named=named)
            time.sleep(SLEEP)
            if x is not None:
                out[a["id"]] = x or {"miss": today.isoformat(), **fallback(a["artist_name"], a["album"], known, named, page)}
            elif known is not None:
                out[a["id"]] = known
        elif known is not None:
            out[a["id"]] = known
    print(f"albums: {sum(1 for v in out.values() if found(v))} found on Deezer, {sum(1 for v in out.values() if is_miss(v))} not; lookups {n}")
    return out


# theneedledrop.com re-posted its 11 Feb - 11 Aug 2015 reviews on these days (lmn/tnd_missing.py); such a review's
# own embedded video is up to ~4 months older than the post, and that older date is the right one
REPOSTED = {"2015-06-20", "2015-06-21"}
VIDEO_GAP_DAYS = 45  # theneedledrop.com posts a review 1 hour to 23 days after the video (median 38 h, 2026); a wider gap is a wrong match


def utc(iso):
    """An ISO time as "YYYY-MM-DDTHH:MM:SSZ" in UTC, so that dates sort as plain strings (TND writes -04:00, YouTube Z)."""
    t = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone.utc)
    return t.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def use_video_dates(uploads, archive, nts):
    """Order the archive by when the review video came out, not by when theneedledrop.com posted it (the owner,
    2026-11-02: catching up in TND's order jumps around). For each archive review with a known video (its own
    video_id or the one in notes.json), "published" becomes the video's upload time and the site's time is kept in
    "tnd_published"; reviews without a video keep the site's. Every date ends up in UTC with Z. Returns how many
    entries changed. uploads: the channel's videos, or {video id: upload time}."""
    when = uploads if isinstance(uploads, dict) else {v["id"]: v["date"] for v in uploads if v.get("date")}
    changed = 0
    for a in archive:
        if not a.get("published"):
            continue
        before = (a["published"], a.get("tnd_published"))
        site = a.get("tnd_published") or a["published"]
        vid = a.get("video_id") or (nts.get(a["id"]) or {}).get("video_id")
        date = when.get(vid)
        gap = date and datetime.datetime.fromisoformat(utc(site)[:-1]) - datetime.datetime.fromisoformat(utc(date)[:-1])
        if date and (abs(gap) <= datetime.timedelta(days=VIDEO_GAP_DAYS)
                     or (vid == a.get("video_id") and utc(site)[:10] in REPOSTED and datetime.timedelta(0) < gap <= datetime.timedelta(days=200))):
            a["published"] = utc(date)
            if utc(date) != utc(site):
                a["tnd_published"] = utc(site)
            else:
                a.pop("tnd_published", None)
        else:
            a["published"] = utc(site)
            a.pop("tnd_published", None)
        changed += (a["published"], a.get("tnd_published")) != before
    return changed


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
        n = {"video_id": v["id"], "blurb": blurb(v["desc"]), "fav": fav, "bc": bandcamp(v["desc"])}
        out[a["id"]] = {k: x for k, x in n.items() if x}
    print(f"notes: {len(out)} reviews, {sum(1 for n in out.values() if n.get('blurb'))} with a blurb, "
          f"{sum(1 for n in out.values() if n.get('fav'))} with fav tracks; Deezer lookups {lookups}, Apple lookups {apple}")
    return out


def apply_dates(path, data_dir):
    """python -m lmn.notes dates <video_dates.json>: the step after the specials run (also lmn/rereviews.py). Re-run on every push retry from
    a fresh archive.json, so it never fights check.py's appends."""
    import json
    from pathlib import Path
    data_dir = Path(data_dir)
    archive = json.loads((data_dir / "archive.json").read_text())
    nts = json.loads((data_dir / "notes.json").read_text())
    moved = use_video_dates(json.loads(Path(path).read_text()), archive, nts)
    print(f"archive: {moved} dates changed to the review videos'")
    from . import aoty, rereviews  # the same fresh copy: a second review of an album, a post TND made twice
    # scores first: the links copy each review's score into the other one's "first"/"redo"
    filled = aoty.fill_scores(archive, json.loads((data_dir / "aoty.json").read_text())) if (data_dir / "aoty.json").exists() else 0
    print(f"archive: Fantano's score taken from the music-database table for {filled} reviews")
    genres = 0
    if (data_dir / "aoty_top.json").exists():  # up to three genres where the archive has one or none (owner, 2026-11-08)
        from . import aoty_top
        genres = aoty_top.fill_genres(archive, json.loads((data_dir / "aoty_top.json").read_text()))
        print(f"archive: genres from the second music-database table for {genres} reviews")
    linked = rereviews.link(archive)
    print(f"archive: {linked} entries got or lost a link to another review of the same album")
    if moved or linked or filled or genres:
        (data_dir / "archive.json").write_text(json.dumps(archive, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    import os
    if sys.argv[1:2] == ["dates"]:
        apply_dates(sys.argv[2], os.environ.get("DATA_DIR", "data"))
