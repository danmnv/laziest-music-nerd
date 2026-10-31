"""Listening links. Every lookup is optional: on failure the button is just not shown."""
import os
import urllib.parse

from . import http
from .musicbrainz import norm


def deezer_album(artist, album):
    q = urllib.parse.quote(f'artist:"{artist}" album:"{album}"')
    try:
        d = http.get_json(f"https://api.deezer.com/search/album?q={q}&limit=5")
    except http.HttpError:
        return None
    na, nt = norm(artist), norm(album)
    for a in d.get("data", []):
        if norm(a.get("title")) == nt and norm((a.get("artist") or {}).get("name")) == na:
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


def ytmusic_search(artist, album):
    return "https://music.youtube.com/search?" + urllib.parse.urlencode({"q": f"{artist} {album}"})
