"""Listening links. Every lookup is optional: on failure the button is just not shown."""
import os
import re
import unicodedata
import urllib.parse

from . import http
from .musicbrainz import norm


CREDIT_SPLIT = re.compile(r"\s*(?:&|,|\+|\||\bx\b|\bwith\b|\bfeat\.?|\band\b)\s*", re.I)
EDITION = (r"(?:(?:\d{4}\s+)?(?:digitally\s+)?remaster(?:ed)?|(?:super\s+)?deluxe|expanded|"
           r"(?:\d+(?:st|nd|rd|th)\s+)?anniversary|special|bonus(?:\s+track)?)(?:\s+edition)?")
BRACKET_EDITION = re.compile(r"\s*[\[(]" + EDITION + r"[\])]\s*$", re.I)
PLAIN_EDITION = re.compile(r"\s+(?:[-–]\s+)?" + EDITION + r"\s*$", re.I)


def credited_names(artist):
    """The names an album may be credited to on Deezer: the full name first, then each artist of a collaboration
    ("Nas & DJ Premier" is an album of "Nas" there). The same rules as worker/src/deezer.mjs."""
    parts = [x.strip() for x in CREDIT_SPLIT.split(artist or "") if x and x.strip()]
    return [artist] + (parts if len(parts) > 1 else [])


def self_titled(artist, album):
    """Fantano writes "Self-Titled" where the album is called after the artist ("Megadeth — Self-Titled")."""
    m = re.match(r"(?i)^self[- ]?titled\b(.*)$", (album or "").strip())
    return f"{artist}{m.group(1)}" if m else album


def album_title_key(title):
    title = re.sub(r"(?<=\()the\s+(?=[^\s()]+\s+album\))", "", title or "", flags=re.I)
    folded = (ch for ch in unicodedata.normalize("NFKD", title) if not unicodedata.combining(ch))
    return "".join(ch for ch in "".join(folded).lower().replace("&", "and") if ch.isalnum())


def album_title_matches(title, want, editions=False):
    """Preserve release names in brackets, such as (Teal Album) or (LP3)."""
    if not want:
        return False
    if album_title_key(title) == want:
        return True
    bracketed = BRACKET_EDITION.sub("", title or "")
    return (album_title_key(bracketed) == want
            or (editions and album_title_key(PLAIN_EDITION.sub("", bracketed)) == want))


def _rank(want):
    return lambda x: (x.get("record_type") != "single", album_title_key(x.get("title")) == want, x.get("nb_tracks") or 0)


def pick_album(results, names, album, editions=False):
    """Prefer a matching album to a same-title single, then the exact title to a standard edition suffix."""
    want = album_title_key(album)
    for key in [norm(n) for n in names if norm(n)]:
        mine = [x for x in results or [] if x and norm((x.get("artist") or {}).get("name")) == key]
        hits = [x for x in mine if album_title_matches(x.get("title"), want, editions)]
        hit = max(hits, key=_rank(want), default=None)
        if hit:
            return hit
    return None


def find_album(artist, album, get=None, editions=False, sleep=None):
    """The album's entry in Deezer's search, or None. Plain words first: Deezer's field search (artist:"…" album:"…")
    answers nothing for many albums it has (checked from Actions 2026-11-02: Taylor Swift "The Life of a Showgirl",
    Angine de Poitrine "Vol. II", Ghost "Skeletá"), so it is only the second try. Request errors are raised."""
    get = get or http.get_json
    want, names = self_titled(artist, album), credited_names(artist)
    # the title alone last: Deezer's search finds nothing for "Destroyer Kaputt" or "Women Public Strain" but finds them by
    # the title (checked from Actions 2026-11-08); pick_album still wants the artist's name
    queries = [f"{artist} {want}", f'artist:"{names[1] if len(names) > 1 else names[0]}" album:"{want}"', want]
    for i, q in enumerate(queries):
        if i and sleep:
            sleep()
        hit = pick_album(get("https://api.deezer.com/search/album?q=" + urllib.parse.quote(q) + "&limit=25").get("data"), names, want, editions)
        if hit:
            return hit
    return None


def _track_key(t):
    """A track's name without guests, brackets and "Part"/"Pt." ("BURGUNDY FT. VINCE STAPLES" = "Burgundy (feat. Vince
    Staples)", "KANNON PT. 2" = "Kannon2")."""
    t = re.sub(r"\s*[(\[].*$", "", t or "")
    t = re.split(r"(?i)\s+(?:ft\.?|feat\.?|featuring)\s", t)[0]
    return norm(re.sub(r"(?i)\b(?:part|pt)\b\.?", "", t))


def fits(named, tracks):
    """Whether a tracklist can be the album Fantano reviewed, given the tracks he names (FAV TRACKS, LEAST FAV TRACK).
    Deezer may have only a single under the album's title, before the album or instead of it (Wolves in the Throne Room
    «Estuary», 2026-11-10: 2 tracks and the single's cover; 67 archive albums on 2026-11-10, e.g. Paramore «This Is
    Why», 1 track): a short tracklist (5 or fewer) without most of the named tracks is not the album. A longer one, or
    too few names, always fits; a remark in place of a track («I don't have one, honestly») is not a name."""
    keys = {_track_key(t) for t in named or [] if len(t or "") <= 60}
    keys = {k for k in keys if len(k) > 2}
    if len(keys) < 2 or not tracks or len(tracks) > 5:
        return True
    have = [_track_key(t.get("title") if isinstance(t, dict) else t[0]) for t in tracks]
    found = sum(1 for k in keys if any(k == h or (len(h) > 3 and (k in h or h in k)) for h in have))
    return found * 2 >= len(keys)


def deezer_album(artist, album):
    try:
        a = find_album(artist, album)
    except http.HttpError:
        return None
    if a:
        try:
            full = http.get_json(f"https://api.deezer.com/album/{a['id']}")
        except http.HttpError:
            full = {}
        return {
            "id": a["id"],
            "url": f"https://www.deezer.com/album/{a['id']}",
            "cover": full.get("cover_xl") or a.get("cover_xl"),
            "duration_min": round(full["duration"] / 60) if full.get("duration") else None,
            "record_type": full.get("record_type") or a.get("record_type"),
            "tracks": [{"title": t.get("title"), "sec": t.get("duration")} for t in (full.get("tracks") or {}).get("data", [])] or None,
        }
    return None


def songlink(deezer_url):
    """song.link's public API now answers 401 without a key; the web page still works for any platform URL."""
    if not deezer_url:
        return None
    key = os.environ.get("ODESLI_API_KEY")
    if key:
        try:
            d = http.get_json("https://api.song.link/v1-alpha.1/links?" + urllib.parse.urlencode({"url": deezer_url, "key": key}))
            return d.get("pageUrl")
        except http.HttpError as e:
            print(f"song.link API: HTTP {e.status}")
    return "https://album.link/" + deezer_url


def bandcamp_search(artist, album):
    # bandcamp.com/search sits behind a JavaScript challenge for scripts, so we cannot verify a match from GitHub Actions.
    # A search link still opens fine in a browser.
    return "https://bandcamp.com/search?" + urllib.parse.urlencode({"q": f"{artist} {album}", "item_type": "a"})


def _apple_matches(row, artist, album):
    title = row.get("collectionName") or ""
    return (norm(row.get("artistName")) == artist and not title.endswith(" - Single")
            and album_title_matches(re.sub(r" - EP$", "", title), album))


def apple_find(artist, album):
    """The album's page on Apple Music, from Apple's public iTunes Search API (no key; made for linking to the store):
    the URL, 0 when Apple has no such album, None when the request failed. Only an exact artist and title match
    ("Self-Titled" is the artist's name; a collaboration may be under one of its artists, as in find_album);
    "Title - Single" is never the album."""
    want, names = self_titled(artist, album), credited_names(artist)
    try:
        d = http.get_json("https://itunes.apple.com/search?" + urllib.parse.urlencode(
            {"term": f"{artist} {want}", "entity": "album", "limit": 10}), timeout=15, retries=0)
    except (http.HttpError, ValueError):
        return None
    nt = album_title_key(want)
    for na in [norm(n) for n in names if norm(n)]:
        hits = [x for x in d.get("results", []) if _apple_matches(x, na, nt) and x.get("collectionViewUrl")]
        hit = max(hits, key=lambda x: album_title_key(x["collectionName"]) == nt, default=None)
        if hit:
            return hit["collectionViewUrl"].split("?")[0]
    return 0


def apple_tracks(url, artist=None, album=None):
    """The tracklist and cover of an album on Apple Music, by its page's URL (iTunes lookup API, no key): {"tracks":
    [{"title", "sec"}], "cover": 1000×1000 artwork URL}, or None. Apple lists an album's whole tracklist even before its
    release (Wolves in the Throne Room «Estuary», 2026-11-10: Deezer had only a 2-track single, MusicBrainz nothing)."""
    m = re.search(r"/album/(?:[^/]+/)?(\d+)", url or "")
    if not m:
        return None
    try:
        d = http.get_json(f"https://itunes.apple.com/lookup?id={m.group(1)}&entity=song&limit=200", timeout=15, retries=0)
    except (http.HttpError, ValueError):
        return None
    res = d.get("results") or []
    collection = next((x for x in res if x.get("wrapperType") == "collection"), {})
    if artist and album:
        want = album_title_key(self_titled(artist, album))
        if not any(_apple_matches(collection, norm(name), want) for name in credited_names(artist)):
            return None
    songs = sorted((x for x in res if x.get("wrapperType") == "track"), key=lambda x: (x.get("discNumber") or 1, x.get("trackNumber") or 0))
    art = collection.get("artworkUrl100")
    tracks = [{"title": x.get("trackName") or "", "sec": round((x.get("trackTimeMillis") or 0) / 1000) or None} for x in songs]
    out = {"tracks": tracks, "cover": art.replace("100x100bb", "1000x1000bb") if art else None}
    return out if tracks or out["cover"] else None


def apple_album(artist, album):
    """apple_find without the difference between "not there" and "failed": the URL or None."""
    return apple_find(artist, album) or None


def ytmusic_search(artist, album):
    return "https://music.youtube.com/search?" + urllib.parse.urlencode({"q": f"{artist} {album}"})
