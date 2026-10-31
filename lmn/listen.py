"""Where Fantano's "Listen:" link leads: a free way to hear the album, and the artist's own release page.

Measured 2026-10-31 on 307 reviews (May 2025 - Oct 2026): "Listen:" leads to YouTube in 62% of them and to
Bandcamp in 37%. The artist's YouTube video usually links a release page of the label or artist (lnk.to, ffm.to
and the like) that lists every service; of 120 such links opened without a browser, 95 showed links to three or
more services in their HTML. A track video may link the single rather than the album, so a page counts only if its
title names the album.
"""
import html
import os
import re
import urllib.parse

from . import http
from .musicbrainz import is_smartlink, norm

URL = re.compile(r"https?://[^\s<>\"')\]]+")
BROWSER_UA = "Mozilla/5.0 (compatible; LaziestMusicNerd/1.0; +https://github.com/danmnv/laziest-music-nerd)"


def youtube_target(url):
    """("playlist", id) or ("video", id) for a YouTube / YouTube Music link, else None."""
    if not url:
        return None
    p = urllib.parse.urlparse(url)
    host = p.netloc.lower().removeprefix("www.").removeprefix("m.")
    if host not in ("youtube.com", "music.youtube.com", "youtu.be"):
        return None
    q = urllib.parse.parse_qs(p.query)
    if host == "youtu.be" and len(p.path.strip("/")) >= 11:
        return "video", p.path.strip("/")[:11]
    if q.get("v"):
        return "video", q["v"][0]
    if q.get("list"):
        return "playlist", q["list"][0]
    return None


def _page_title(url):
    page = http.request(url, headers={"User-Agent": BROWSER_UA}, timeout=15, retries=0)
    titles = re.findall(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', page) + re.findall(r"<title[^>]*>(.*?)</title>", page, re.S)
    return " ".join(html.unescape(t) for t in titles)


def resolve(listen_url, album, max_pages=3):
    """From a YouTube "Listen:" link: {"youtube_album": the link, if it is a playlist named after the album,
    "release_page": the release page linked from the artist's video, if its title names the album}."""
    out = {}
    target = youtube_target(listen_url)
    key = album and norm(album)
    if not target or not key or not (os.environ.get("YOUTUBE_API_KEY") or "").strip():
        return out
    from .yt_archive import yt
    kind, ident = target
    if kind == "playlist":
        pl = yt("playlists", part="snippet", id=ident).get("items") or []
        if pl and key in norm(pl[0]["snippet"].get("title")):
            out["youtube_album"] = listen_url
        items = yt("playlistItems", part="contentDetails", playlistId=ident, maxResults=1).get("items") or []
        if not items:
            return out
        ident = items[0]["contentDetails"]["videoId"]
    videos = yt("videos", part="snippet", id=ident).get("items") or []
    desc = videos[0]["snippet"].get("description", "") if videos else ""
    seen = []
    for u in URL.findall(desc):
        u = u.rstrip(".,;")
        if is_smartlink(u) and u not in seen:
            seen.append(u)
    for u in seen[:max_pages]:
        try:
            title = _page_title(u)
        except Exception as ex:  # a dead or blocked page: try the next one
            print(f"release page {urllib.parse.urlparse(u).netloc}: {type(ex).__name__} {getattr(ex, 'status', '')}")
            continue
        if key in norm(title):
            out["release_page"] = u
            break
    return out
