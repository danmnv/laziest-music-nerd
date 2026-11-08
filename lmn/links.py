"""Listening links. Every lookup is optional: on failure the button is just not shown."""
import os
import re
import urllib.parse

from . import http
from .musicbrainz import norm


CREDIT_SPLIT = re.compile(r"\s*(?:&|,|\+|\||\bx\b|\bwith\b|\bfeat\.?|\band\b)\s*", re.I)
EDITION = re.compile(r"\b(deluxe|expanded|edition|remaster(ed)?|anniversary|bonus|special)\b", re.I)


def credited_names(artist):
    """The names an album may be credited to on Deezer: the full name first, then each artist of a collaboration
    ("Nas & DJ Premier" is an album of "Nas" there). The same rules as worker/src/deezer.mjs."""
    parts = [x.strip() for x in CREDIT_SPLIT.split(artist or "") if x and x.strip()]
    return [artist] + (parts if len(parts) > 1 else [])


def self_titled(artist, album):
    """Fantano writes "Self-Titled" where the album is called after the artist ("Megadeth — Self-Titled")."""
    m = re.match(r"(?i)^self[- ]?titled\b(.*)$", (album or "").strip())
    return f"{artist}{m.group(1)}" if m else album


def _rank(want):
    return lambda x: (x.get("record_type") != "single", norm(x.get("title")) == want, x.get("nb_tracks") or 0)


def pick_album(results, names, album, editions=False):
    """The result for this album: the same title, or the title before a bracket ("Kid A (Remastered)"); with
    editions, also a title that starts the same and names an edition ("Kid A Deluxe Edition"), never another record
    that merely starts the same ("Kid A Mnesia"). By the full artist name first, then by one of the credited names.
    Of several with the title, the album before a single of the same name (_rank)."""
    want = norm(album)
    for key in [norm(n) for n in names if norm(n)]:
        mine = [x for x in results or [] if x and norm((x.get("artist") or {}).get("name")) == key]
        same = [x for x in mine if norm(x.get("title")) == want or norm(re.sub(r"\s*[(\[].*$", "", x.get("title") or "")) == want]
        # a single named after the album comes first in the search for some (KNEECAP "FENIAN", 2026-11-08: a 3-track
        # single with its own cover): the album itself first, then the exact title, then the longest
        hit = max(same, key=_rank(want), default=None)
        if not hit and editions:
            hit = next((x for x in mine if norm(x.get("title")).startswith(want) and EDITION.search(x.get("title") or "")), None)
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
    nt = norm(want)
    for na in [norm(n) for n in names if norm(n)]:
        for x in d.get("results", []):
            name = x.get("collectionName") or ""
            if name.endswith(" - Single") or norm(x.get("artistName")) != na:
                continue
            if norm(re.sub(r" - EP$", "", name)) == nt or norm(re.sub(r"\s*[(\[][^)\]]*[)\]]\s*$", "", re.sub(r" - EP$", "", name))) == nt:
                return (x.get("collectionViewUrl") or "").split("?")[0] or 0
    return 0


def apple_album(artist, album):
    """apple_find without the difference between "not there" and "failed": the URL or None."""
    return apple_find(artist, album) or None


def ytmusic_search(artist, album):
    return "https://music.youtube.com/search?" + urllib.parse.urlencode({"q": f"{artist} {album}"})
