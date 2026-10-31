"""New reviews from The Needle Drop's YouTube channel, and the plan of what each hourly run adds.

theneedledrop.com posts a review a median of 38 hours after its video (June–October 2026: from 1 hour to 23 days),
and about 8 of ~95 review videos since June never reached the site. So a new review is noticed on YouTube. The video
description carries what a card needs: score, genres, year and label, Fantano's favourite and least favourite tracks,
and often a Bandcamp link. The site post, once it comes, adds the transcript page; text-only staff reviews exist only
on the site.
"""
import os
import re
from datetime import datetime, timedelta, timezone

from . import tnd

CARD_WINDOW = timedelta(days=4)   # a review found later than this goes into the list and the site, but gets no card
LIST_WINDOW = timedelta(days=60)

META = re.compile(r"^(?P<who>[^\n]+?)\s+-\s+(?P<what>[^\n]+?)\s*/\s*(?P<year>(?:19|20)\d\d)\s*/\s*(?P<rest>[^\n]+?)\s*$", re.M)
SCORE_LINE = re.compile(r"^\s*(?P<v>\d{1,2}|[A-Za-z][A-Za-z' ]*?)\s*/\s*10\b(?P<rest>[^\n]*)$", re.M)
FAV = re.compile(r"^\s*FAV(?:ORITE)? TRACKS?:\s*(.+?)\s*$", re.M | re.I)
LEAST = re.compile(r"^\s*LEAST FAV(?:ORITE)? TRACKS?:\s*(.+?)\s*$", re.M | re.I)
LISTEN = re.compile(r"^\s*Listen:\s*(\S+)", re.M | re.I)
GUEST_SIGNOFF = re.compile(r"this is just (?:his|her|their) opinion", re.I)
REVIEW_TITLE = re.compile(r"\b(?:ALBUM|EP|MIXTAPE)\s+REVIEW\s*\]?\s*$|\bis\s+(?:NOT GOOD|BAD|NOT BAD|NOT MUSIC)\s*$|GUEST REVIEW", re.I)
NONE_TRACKS = {"n/a", "none", "any", "nothing", "too many to choose from", "-"}


def latest_uploads(limit=50):
    """The channel's newest uploads, or None without a key or when YouTube fails (then the site is the only source)."""
    if not (os.environ.get("YOUTUBE_API_KEY") or "").strip():
        return None
    from .yt_archive import yt
    try:
        ch = yt("channels", part="contentDetails", forHandle="@theneedledrop")
        uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        d = yt("playlistItems", part="snippet,contentDetails", playlistId=uploads, maxResults=limit)
    except Exception as ex:
        print(f"youtube unavailable ({type(ex).__name__}: {str(ex)[:200]}); using the site only")
        return None
    out = []
    for it in d.get("items", []):
        sn, cd = it.get("snippet", {}), it.get("contentDetails", {})
        thumbs = sn.get("thumbnails") or {}
        out.append({"video_id": cd.get("videoId") or sn.get("resourceId", {}).get("videoId"), "title": sn.get("title", ""),
                    "desc": sn.get("description", ""), "published": cd.get("videoPublishedAt") or sn.get("publishedAt"),
                    "thumb": (thumbs.get("maxres") or thumbs.get("high") or {}).get("url")})
    return [u for u in out if u["video_id"] and u["published"]]


def _tracks(line):
    if not line or line.strip().lower() in NONE_TRACKS:
        return []
    return [t.strip() for t in re.split(r"\s*[,;]\s+", line) if t.strip() and t.strip().lower() not in NONE_TRACKS]


def parse_description(desc):
    desc = desc or ""
    out = {}
    metas = list(META.finditer(desc))
    if metas:
        m = metas[-1]
        parts = [p.strip() for p in m.group("rest").split(" / ")]
        out.update(year=int(m.group("year")), genres=[g.strip().lower() for g in parts[-1].split(",") if g.strip()],
                   label=" / ".join(parts[:-1]) or None, meta_artist=m.group("who").strip(), meta_album=m.group("what").strip())
    scores = list(SCORE_LINE.finditer(desc))
    if scores:
        m = scores[-1]
        v = m.group("v").strip().upper()
        if v.isdigit() and int(v) <= 10:
            out["score"] = int(v)
        elif v in ("NOT GOOD", "BAD", "NOT MUSIC"):
            out["not_good"] = True
        elif v == "CLASSIC":
            out["classic"] = True
        elif v == "NOT BAD":
            out["not_bad"] = True
        else:  # "GIGGENS LOVES IT/10": someone else's verdict
            out["guest"] = True
        if "loved-list" in m.group("rest"):
            out["loved"] = True
    if GUEST_SIGNOFF.search(desc):
        out["guest"] = True
    fav = FAV.search(desc)
    out["fav_tracks"] = _tracks(fav.group(1)) if fav else []
    least = LEAST.search(desc)
    out["least_fav_track"] = (_tracks(least.group(1)) or [None])[0] if least else None
    listen = LISTEN.search(desc)
    if listen:
        out["listen_url"] = listen.group(1)
    return out


def is_review(u):
    return bool(REVIEW_TITLE.search(u.get("title") or "")) and bool(META.search(u.get("desc") or ""))


def review_from_video(u):
    """A review record in the same shape as tnd.parse_post, from a video alone."""
    d = parse_description(u["desc"])
    info = tnd.parse_title(u["title"])
    artist, album = info.get("artist"), info.get("album")
    if not (artist and album):
        artist, album = d.get("meta_artist"), d.get("meta_album")
    rtype = "ep" if re.search(r"\bEP\s+REVIEW", u["title"], re.I) else "mixtape" if re.search(r"\bMIXTAPE\s+REVIEW", u["title"], re.I) else None
    if album and re.search(r"\s+EP$", album):
        rtype, album = rtype or "ep", re.sub(r"\s+EP$", "", album)
    listen = d.get("listen_url") or ""
    host = re.sub(r"^https?://", "", listen).split("/", 1)[0].lower()
    vid = u["video_id"]
    return {
        "id": vid, "source": "youtube", "slug": None, "url": f"https://www.youtube.com/watch?v={vid}", "title": u["title"],
        "artist_name": artist, "album": album, "published": u["published"],
        "score": d.get("score"), "not_good": bool(d.get("not_good") or info.get("not_good_title")),
        "classic": bool(d.get("classic")), "not_bad": bool(d.get("not_bad") or info.get("not_bad_title")), "score_note": None, "type": rtype,
        "genres": d.get("genres", []), "guest": bool(d.get("guest") or info.get("guest") or info.get("staff")),
        "loved": bool(d.get("loved")), "video_id": vid, "excerpt": "", "thumb": u.get("thumb"),
        "fav_tracks": d.get("fav_tracks", []), "least_fav_track": d.get("least_fav_track"),
        "year": d.get("year"), "label": d.get("label"),
        "listen_bandcamp": listen if host == "bandcamp.com" or host.endswith(".bandcamp.com") else None,
    }


def _ts(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def plan(posts, uploads, reviews, seeding, now=None):
    """What this run adds. Returns (new, upgrades).

    new: [{"rev", "text", "card"}] oldest first; card=False means list and site only (seeding, or found too late).
    upgrades: [(review, site_rev)] for reviews first taken from YouTube whose site post has now appeared.
    uploads=None means YouTube is unavailable: every new site post is then handled as before (card unless seeding).
    """
    now = now or datetime.now(timezone.utc)
    fresh = lambda iso: now - _ts(iso) <= CARD_WINDOW
    known_ids = {r["id"] for r in reviews}
    by_video = {r["video_id"]: r for r in reviews if r.get("video_id")}
    site = [(tnd.parse_post(p), p.get("plaintext")) for p in posts]
    site_by_video = {rev["video_id"]: (rev, text) for rev, text in site if rev.get("video_id")}
    new, upgrades, taken = [], [], set()

    reviews_on_yt = {}
    if uploads is not None:
        reviews_on_yt = {u["video_id"]: u for u in uploads if is_review(u)}
        for vid, u in reviews_on_yt.items():
            if vid in by_video or now - _ts(u["published"]) > LIST_WINDOW:
                continue
            match = site_by_video.get(vid)
            if match and match[0]["id"] in known_ids:
                continue
            if match:  # the site already has it: keep its transcript, but the review's date is the video's
                rev, text = dict(match[0], published=u["published"]), match[1]
                taken.add(rev["id"])
            else:
                rev, text = review_from_video(u), None
            new.append({"rev": rev, "text": text, "card": not seeding and fresh(u["published"])})

    for rev, text in site:
        vid = rev.get("video_id")
        if rev["id"] in known_ids or rev["id"] in taken:
            continue
        if vid and vid in by_video:
            old = by_video[vid]
            if old.get("source") == "youtube" and not old.get("tnd_url"):
                upgrades.append((old, rev))
            continue
        if uploads is None:
            new.append({"rev": rev, "text": text, "card": not seeding})
        elif vid and vid in reviews_on_yt:
            continue  # handled above (too old for the list)
        else:
            # A text-only staff review (no video), or a video whose description we didn't recognise as a review,
            # or one older than the newest uploads: a card only if it is fresh by the best date we know.
            u = next((x for x in uploads if x["video_id"] == vid), None) if vid else None
            when = u["published"] if u else rev["published"]
            new.append({"rev": rev, "text": text, "card": not seeding and (u is not None or not vid) and fresh(when)})
    new.sort(key=lambda x: _ts(x["rev"]["published"]))
    return new, upgrades


def apply_upgrade(r, site_rev):
    """The site post of a review first taken from YouTube: link its transcript page, fill what the video lacked."""
    r["tnd_url"], r["slug"], r["tnd_id"] = site_rev["url"], site_rev.get("slug"), site_rev["id"]
    if not r.get("genres") and site_rev.get("genres"):
        r["genres"] = site_rev["genres"]
    if site_rev.get("score_note") and site_rev.get("score") == r.get("score") and not r.get("score_note"):
        r["score_note"] = site_rev["score_note"]
