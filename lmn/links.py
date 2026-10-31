"""Listening links. Every lookup is optional: on failure the button is just not shown."""
import html
import json
import os
import re
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


def is_bandcamp_album(url):
    host = re.sub(r"^https?://", "", url or "").split("/", 1)[0].lower()
    return (host == "bandcamp.com" or host.endswith(".bandcamp.com")) and "/album/" in url


def bandcamp_album(url):
    """Tracklist and length from the artist's own Bandcamp album page (its data-tralbum JSON).
    Album pages open fine from GitHub Actions (checked 2026-10-31 on HMLTD - FANGS, which MusicBrainz,
    Deezer and Apple Music didn't have); only bandcamp.com/search is behind a challenge."""
    if not is_bandcamp_album(url):
        return None
    m = re.search(r'data-tralbum="([^"]+)"', http.request(url))
    if not m:
        return None
    tracks = [{"title": t.get("title"), "sec": round(t["duration"]) if t.get("duration") else None}
              for t in json.loads(html.unescape(m.group(1))).get("trackinfo") or [] if t.get("title")]
    if not tracks:
        return None
    total = sum(t["sec"] or 0 for t in tracks)
    return {"tracks": tracks, "duration_min": round(total / 60) if total and all(t["sec"] for t in tracks) else None}


def bandcamp_search(artist, album):
    # bandcamp.com/search sits behind a JavaScript challenge for scripts, so we cannot verify a match from GitHub Actions.
    # A search link still opens fine in a browser.
    return "https://bandcamp.com/search?" + urllib.parse.urlencode({"q": f"{artist} {album}", "item_type": "a"})


def ytmusic_search(artist, album):
    return "https://music.youtube.com/search?" + urllib.parse.urlencode({"q": f"{artist} {album}"})
