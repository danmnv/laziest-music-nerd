"""Turn a parsed TND post into a full card record. Each source is optional."""
from . import gemini, links, musicbrainz as mb


def enrich(rev, plaintext, archive):
    r = dict(rev)
    ai = gemini.summarize(r["title"], plaintext) or {}
    r["ai"] = {k: ai.get(k) for k in ("brief", "who", "moods") if ai.get(k)}
    if not r.get("artist_name") and ai.get("artist"):
        r["artist_name"], r["album"] = ai["artist"], ai.get("album")
    if not r.get("artist_name"):
        r["artist_name"], r["album"] = r["title"], ""
    artist, album = r["artist_name"], r["album"] or ""

    rg = mb.find_release_group(artist, album) if album else None
    r["artist"] = {}
    r["links"] = {}
    if rg:
        r["mb_release_group"] = rg["rg_id"]
        det = mb.release_details(rg["releases"])
        r["duration_min"] = det["duration_min"]
        if det["bandcamp"]:
            r["links"]["bandcamp"] = det["bandcamp"]
        info = mb.artist_info(rg["artist_id"]) or {}
        r["artist"] = {"mbid": rg["artist_id"], **{k: info.get(k) for k in ("type", "country", "area", "begin", "end", "aliases")}}
        if not r.get("type"):
            sec = [s.lower() for s in rg.get("secondary") or []]
            r["type"] = {"EP": "ep", "Single": "single"}.get(rg.get("type")) or ("live" if "live" in sec else "mixtape" if "mixtape/street" in sec else None)

    dz = links.deezer_album(artist, album) if album else None
    if dz:
        r["links"]["songlink"] = links.songlink(dz["url"])
        r["duration_min"] = r.get("duration_min") or dz["duration_min"]
    r["links"].setdefault("bandcamp", links.bandcamp_search(artist, album))
    r["links"]["ytmusic"] = links.ytmusic_search(artist, album)

    r["covers"] = [c for c in [
        dz and dz.get("cover"),
        rg and mb.cover_url(rg["rg_id"]),
        r.get("thumb"),
    ] if c]
    prev, unsure = previous_reviews(r, archive)
    r["previous"], r["previous_unsure"] = prev, unsure
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
            found = mb.find_release_group(a["artist_name"], a["album"])
            a["artist_mbid"] = found["artist_id"] if found else None
        if a.get("artist_mbid") == mbid:
            verified.append({k: a.get(k) for k in ("album", "score", "not_good", "classic", "url", "published")})
        else:
            unsure += 1
    return verified, unsure


def archive_entry(rev):
    return {k: rev.get(k) for k in ("id", "url", "published", "artist_name", "album", "score", "not_good", "classic", "guest")}
