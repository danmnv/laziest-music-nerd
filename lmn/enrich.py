"""Turn a parsed TND post into a full card record. Each source is optional: one failing source only empties its own fields."""
from . import gemini, links, musicbrainz as mb


def _try(name, fn, default=None):
    try:
        return fn()
    except Exception as ex:  # bad JSON, timeout, an API change: log it and keep the other sources' fields
        print(f"{name} failed: {type(ex).__name__}: {str(ex)[:200]}")
        return default


def enrich(rev, plaintext, archive, use_ai=True):
    r = dict(rev)
    ai = (_try("gemini", lambda: gemini.summarize(r["title"], plaintext)) if use_ai else None) or {}
    r["ai"] = {k: ai.get(k) for k in ("brief", "who", "moods", "best_tracks") if ai.get(k)}
    if not r.get("artist_name") and ai.get("artist"):
        r["artist_name"], r["album"] = ai["artist"], ai.get("album")
    if not r.get("artist_name"):
        r["artist_name"], r["album"] = r["title"], ""
    artist, album = r["artist_name"], r["album"] or ""

    rg = _try("musicbrainz search", lambda: mb.find_release_group(artist, album)) if album else None
    r["artist"] = {}
    r["links"] = {}
    if rg:
        r["mb_release_group"] = rg["rg_id"]
        det = _try("musicbrainz release", lambda: mb.release_details(rg["releases"]), {})
        r["duration_min"] = det.get("duration_min")
        r["tracks"] = det.get("tracks")
        if det.get("bandcamp"):
            r["links"]["bandcamp"] = det["bandcamp"]
        if det.get("smartlink"):
            r["links"]["songlink"] = det["smartlink"]  # the artist's own all-platforms page, if MusicBrainz knows it
        info = _try("musicbrainz artist", lambda: mb.artist_info(rg["artist_id"])) or {}
        r["artist"] = {"mbid": rg["artist_id"], **{k: info.get(k) for k in ("type", "country", "area", "begin", "end", "aliases")}}
        if not r.get("type"):
            sec = [s.lower() for s in rg.get("secondary") or []]
            r["type"] = {"EP": "ep"}.get(rg.get("type")) or ("live" if "live" in sec else "mixtape" if "mixtape/street" in sec else None)

    dz = _try("deezer", lambda: links.deezer_album(artist, album)) if album else None
    if dz:
        r["links"].setdefault("songlink", links.songlink(dz["url"]))
        r["duration_min"] = r.get("duration_min") or dz.get("duration_min")
        r["tracks"] = r.get("tracks") or dz.get("tracks")
    r["links"].setdefault("bandcamp", links.bandcamp_search(artist, album))
    r["links"]["ytmusic"] = links.ytmusic_search(artist, album)

    r["covers"] = [c for c in [
        dz and dz.get("cover"),
        rg and mb.cover_url(rg["rg_id"]),
        r.get("thumb"),
    ] if c]
    r["previous"], r["previous_unsure"] = _try("previous reviews", lambda: previous_reviews(r, archive), ([], 0))
    return r


def previous_reviews(r, archive, max_checks=10):
    """Earlier Fantano reviews of the same artist, matched by MusicBrainz artist ID."""
    names = {mb.norm(r["artist_name"])} | {mb.norm(a) for a in (r.get("artist") or {}).get("aliases") or []}
    names.discard("")
    cands = [a for a in archive
             if a["id"] != r["id"] and not a.get("guest") and a["published"] < r["published"]
             and mb.norm(a.get("artist_name")) in names]
    cands.sort(key=lambda a: a["published"], reverse=True)
    mbid = (r.get("artist") or {}).get("mbid")
    if not mbid:
        return [], len(cands)
    verified, unsure, checks = [], 0, 0
    for a in cands:
        if "artist_mbid" not in a and checks < max_checks and a.get("album"):
            checks += 1
            try:
                found = mb.find_release_group(a["artist_name"], a["album"])
            except Exception as ex:  # unknown this time, try again with the next review of this artist
                print(f"musicbrainz check of an earlier review failed: {type(ex).__name__}")
            else:
                a["artist_mbid"] = found["artist_id"] if found else None
        if a.get("artist_mbid") == mbid:
            verified.append({k: a.get(k) for k in ("album", "score", "not_good", "classic", "url", "published")})
        else:
            unsure += 1
    return verified, unsure


def archive_entry(rev):
    return {k: rev.get(k) for k in ("id", "url", "published", "artist_name", "album", "score", "not_good", "classic", "guest", "genres")}
