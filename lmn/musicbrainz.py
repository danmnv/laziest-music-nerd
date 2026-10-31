"""MusicBrainz lookups. Max 1 request/second, User-Agent required. Any failure -> None."""
import re
import time
import urllib.parse
import unicodedata

from . import http

BASE = "https://musicbrainz.org/ws/2"
_last = [0.0]


def _get(path, **params):
    wait = 1.1 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    params["fmt"] = "json"
    return http.get_json(f"{BASE}/{path}?{urllib.parse.urlencode(params)}")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "", s)


def _q(s):
    return '"' + s.replace('"', " ").replace("\\", " ") + '"'


def find_release_group(artist, album):
    """Return dict(rg_id, artist_id, artist_name, title, type, date) or None if not confidently matched."""
    try:
        res = _get("release-group", query=f"releasegroup:{_q(album)} AND artist:{_q(artist)}", limit=5)
    except http.HttpError as e:
        print(f"musicbrainz search failed: {e.status}")
        return None
    na, nt = norm(artist), norm(album)
    for rg in res.get("release-groups", []):
        credit = rg.get("artist-credit") or []
        names = norm("".join(c.get("name", "") + c.get("joinphrase", "") for c in credit))
        first = credit[0]["artist"] if credit and "artist" in credit[0] else None
        if rg.get("score", 0) >= 90 and norm(rg.get("title")) == nt and first and (names == na or norm(first["name"]) == na or na in names):
            return {
                "rg_id": rg["id"],
                "artist_id": first["id"],
                "artist_name": first["name"],
                "title": rg.get("title"),
                "type": rg.get("primary-type"),
                "secondary": rg.get("secondary-types", []),
                "date": rg.get("first-release-date"),
                "releases": [r["id"] for r in rg.get("releases", [])],
            }
    return None


def artist_info(artist_id):
    try:
        d = _get(f"artist/{artist_id}", inc="aliases+release-groups")
    except http.HttpError:
        return None
    span = d.get("life-span") or {}
    rgs = [rg for rg in d.get("release-groups", []) if rg.get("primary-type") == "Album" and not rg.get("secondary-types")]
    return {
        "type": d.get("type"),
        "country": d.get("country"),
        "area": (d.get("area") or {}).get("name"),
        "begin": span.get("begin"),
        "end": span.get("end"),
        "aliases": sorted({a["name"] for a in d.get("aliases", []) if a.get("name") != d.get("name")})[:6],
        "albums": sorted((rg.get("first-release-date") or "", rg["id"], rg.get("title")) for rg in rgs),
    }


def cover_url(rg_id):
    return f"https://coverartarchive.org/release-group/{rg_id}/front-500"


def release_details(release_ids):
    """Duration (minutes) and Bandcamp URL from the first release with full track lengths."""
    out = {"duration_min": None, "bandcamp": None}
    for rid in release_ids[:3]:
        try:
            d = _get(f"release/{rid}", inc="recordings+url-rels")
        except http.HttpError:
            continue
        for rel in d.get("relations", []):
            u = (rel.get("url") or {}).get("resource", "")
            if "bandcamp.com" in u and not out["bandcamp"]:
                out["bandcamp"] = u
        tracks = [t for m in d.get("media", []) for t in m.get("tracks", [])]
        if not out["duration_min"] and tracks and all(t.get("length") for t in tracks):
            out["duration_min"] = round(sum(t["length"] for t in tracks) / 60000)
        if out["duration_min"] and out["bandcamp"]:
            break
    return out
