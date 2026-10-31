"""The Needle Drop: fetch album reviews via the site's public Ghost Content API and parse them."""
import html as htmlmod
import json
import re
import urllib.parse

from . import http
from .musicbrainz import norm

SITE = "https://theneedledrop.com"
API = f"{SITE}/ghost/api/content"
_key = [None]


def content_key():
    """The Content API key is public: Ghost embeds it in every page for the site's own search."""
    if not _key[0]:
        page = http.request(SITE + "/")
        m = re.search(r'data-key="([0-9a-f]{20,})"', page)
        if not m:
            raise RuntimeError("TND: Ghost content key not found on the home page")
        _key[0] = m.group(1)
    return _key[0]


def fetch_posts(limit=15, page=1, with_text=False, since=None):
    params = {
        "key": content_key(), "limit": limit, "page": page, "include": "tags",
        "filter": "tag:album-reviews" + (f"+published_at:>'{since}'" if since else ""),
        "fields": "id,title,slug,published_at,url,canonical_url,custom_excerpt,feature_image" + (",html" if with_text else ""),
    }
    if with_text:
        params["formats"] = "html,plaintext"
        params["fields"] += ",plaintext"
    return http.get_json(f"{API}/posts/?{urllib.parse.urlencode(params)}")


def fetch_all_light():
    out, page = [], 1
    while page:
        d = fetch_posts(limit=100, page=page)
        out += d["posts"]
        page = d["meta"]["pagination"]["next"]
    return out


# ---------- parsing ----------

SKIP_TAGS = {"album reviews", "loved list", "great albums", "guest reviews", "giggens", "not good", "not bad", "classic",
             "classics", "classics week", "classic review", "classic/10", "review", "reviews", "album review", "video review",
             "album", "new", "ep", "ep review", "ep reviews", "mixtape", "mixtape review", "live", "live album",
             "compilation", "single", "single review", "singles", "soundtrack", "soundtrack review", "deluxe", "remix",
             "remixes", "band", "collaboration", "idek", "#$"}
TYPE_TAGS = {"ep": "ep", "ep review": "ep", "ep reviews": "ep", "mixtape": "mixtape", "mixtape review": "mixtape",
             "live": "live", "live album": "live", "compilation": "compilation", "soundtrack": "soundtrack",
             "soundtrack review": "soundtrack", "single": "single", "single review": "single"}
SCORE_TAG = re.compile(r"^\s*(?:decent\s+)?(\d{1,2})\s*/\s*10\s*$|^\s*decent\s+(\d{1,2})\s*$", re.I)
VERDICT = re.compile(
    r"(?:feeling|giving|i'?m at|it'?s an?)\s+(?:an?\s+)?"
    r"(?P<note>(?:very\s+)?(?:light|decent|strong|solid)(?:[\s-]+to[\s-]+(?:a\s+)?(?:light|decent|strong|solid))?[\s-]+)?"
    r"(?P<n>10|[0-9])\b(?!\s*(?:years|tracks|songs|minutes|albums|records))", re.I)


def parse_title(title):
    t = htmlmod.unescape(title).strip()
    info = {"guest": False, "staff": False, "not_good_title": False}
    if re.search(r"guest review", t, re.I):
        info["guest"] = True
        t = re.sub(r"\s*[\(\[]?(?:split\s+)?guest review[\)\]]?\s*$", "", t, flags=re.I)
    m = re.match(r"^TND staff album review:\s*['‘’\"](.+?)['‘’\"]\s+by\s+(.+)$", t, re.I)
    if m:
        info.update(staff=True, artist=m.group(2).strip(), album=m.group(1).strip())
        return info
    m = re.match(r"^(.+?)['’]s?\s+(.+?)\s+is\s+(NOT GOOD|BAD|NOT MUSIC|NOT BAD)\s*$", t)
    if m:
        verdict = "not_bad_title" if m.group(3) == "NOT BAD" else "not_good_title"
        info.update({verdict: True, "artist": m.group(1).strip(), "album": m.group(2).strip()})
        return info
    t = re.sub(r"\s+(?:ALBUM|EP|MIXTAPE)\s+REVIEW\s*$", "", t, flags=re.I)
    m = re.match(r"^(.+?)\s*[-–—]\s+(.+)$", t) or re.match(r"^(.+?)\s+[-–—]\s*(.+)$", t)
    if m:
        info.update(artist=m.group(1).strip(), album=m.group(2).strip())
    return info


def parse_verdict(text):
    """Look at the end of the transcript for 'light-to-decent 7', 'strong 8', NOT GOOD, CLASSIC."""
    tail = (text or "")[-900:]
    out = {}
    m = None
    for m in VERDICT.finditer(tail):
        pass
    if m:
        out["score"] = int(m.group("n"))
        if m.group("note"):
            out["note"] = re.sub(r"\s+", " ", m.group("note").strip(" -")).lower()
    if re.search(r"\bNOT GOOD\b", tail):
        out["not_good"] = True
    if re.search(r"\bCLASSIC\b", tail):
        out["classic"] = True
    return out


def parse_post(p):
    tags = [htmlmod.unescape(t["name"]) for t in p.get("tags", [])]
    low = [t.lower() for t in tags]
    info = parse_title(p["title"])
    score = None
    for t in tags:
        m = SCORE_TAG.match(t)
        if m:
            score = int(m.group(1) or m.group(2))
            break
    not_good = "not good" in low or info["not_good_title"]
    classic = "classic/10" in low or ("classic" in low and score is None and "classic review" not in low and "classics week" not in low)
    text = p.get("plaintext") or ""
    verdict = parse_verdict(text) if text else {}
    if score is None and not not_good and not classic:
        score = verdict.get("score")
        not_good = verdict.get("not_good", False)
    rtype = None
    for t in low:
        if t in TYPE_TAGS:
            rtype = TYPE_TAGS[t]
            break
    album = info.get("album")
    if album and re.search(r"\s+EP$", album):
        rtype = rtype or "ep"
        album = re.sub(r"\s+EP$", "", album)
    artist = info.get("artist")
    skip = {norm(artist or ""), norm(album or "")}
    genres = []
    for t in tags:
        tl = t.lower()
        if (tl in SKIP_TAGS or tl.startswith("edited by") or SCORE_TAG.match(t) or re.fullmatch(r"\d{1,4}", tl)
                or norm(t) in skip or t.startswith("#")):
            continue
        genres.append(t)
    video = None
    for src in (p.get("canonical_url") or "", p.get("html") or ""):
        m = re.search(r"(?:watch\?v=|youtu\.be/|/embed/)([\w-]{11})", htmlmod.unescape(src))
        if m:
            video = m.group(1)
            break
    guest = info["guest"] or info["staff"] or "guest reviews" in low
    return {
        "id": p["id"],
        "slug": p["slug"],
        "url": p["url"],
        "title": htmlmod.unescape(p["title"]),
        "artist_name": artist,
        "album": album,
        "published": p["published_at"],
        "score": score,
        "not_good": bool(not_good),
        "classic": bool(classic),
        "not_bad": bool(info.get("not_bad_title") or ("not bad" in low and score is None and not not_good)),
        "score_note": verdict.get("note") if verdict.get("score") == score else None,
        "type": rtype,
        "genres": genres,
        "guest": guest,
        "loved": "loved list" in low,
        "video_id": video,
        "excerpt": htmlmod.unescape(p.get("custom_excerpt") or ""),
        "thumb": p.get("feature_image"),
    }
