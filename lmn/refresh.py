"""Fill in a card after it went out: what was missing then (Gemini failed or was out of its daily limit, the album
was not yet in MusicBrainz or Deezer). Only empty fields are filled; nothing a reader has already seen is replaced.

When a review is looked up again (a "stage"):
- "site": its post appeared on theneedledrop.com (the transcript is a steadier input for Gemini than the video);
- "1d" and "3d": one and three days after the review, also for reviews the site never posts.
The channel post is then edited in place, which notifies no one. The site and the pinned list are rebuilt from
reviews.json as usual.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone

from . import card

STAGES = (("3d", timedelta(days=3)), ("1d", timedelta(days=1)))  # latest first
WINDOW = timedelta(days=7)   # older reviews stay as they are
MAX_PER_RUN = 3              # each may wait up to 4 minutes for Gemini
MAX_TRIES = 3                # a channel post that can't be edited is given up after this many hours


def _ts(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def passed_stages(r, now=None):
    """The timed stages already behind a review; a card posted late has nothing to look up again for them."""
    age = (now or datetime.now(timezone.utc)) - _ts(r["published"])
    return [name for name, at in STAGES if age >= at]


def due(r, now=None):
    """The stage this review is waiting for, or None."""
    done = set(r.get("refreshed") or [])
    if r.get("tnd_url") and "site" not in done:
        return "site"
    age = (now or datetime.now(timezone.utc)) - _ts(r["published"])
    if age > WINDOW:
        return None
    for name, at in STAGES:
        if age >= at:
            return None if name in done else name
    return None


def mark(r, stage):
    done = set(r.get("refreshed") or []) | {stage}
    if stage == "3d":
        done.add("1d")
    r["refreshed"] = sorted(done)
    r.pop("refresh_tries", None)


def missing(r):
    """What a later lookup may fill."""
    links = r.get("links") or {}
    out = []
    if r.get("tg_channel_msg") and not (r.get("ai") or {}).get("brief"):
        out.append("brief")  # Gemini is spent only on reviews that have a card
    if not r.get("tracks") or not r.get("duration_min"):
        out.append("tracks")
    if not links.get("songlink"):
        out.append("songlink")
    if "bandcamp.com/search" in (links.get("bandcamp") or ""):
        out.append("bandcamp")
    return out


def fill(r, fresh):
    """Copy into r what fresh (a new enrich() of the same review) found and r lacks."""
    ai = r.setdefault("ai", {})
    for k, v in (fresh.get("ai") or {}).items():
        if v and not ai.get(k):
            ai[k] = v
    for k in ("score_note", "tracks", "duration_min", "mb_release_group", "type"):
        if fresh.get(k) and not r.get(k):
            r[k] = fresh[k]
    if (fresh.get("artist") or {}).get("mbid") and not (r.get("artist") or {}).get("mbid"):
        r["artist"] = fresh["artist"]
        r["previous"], r["previous_unsure"] = fresh.get("previous", []), fresh.get("previous_unsure", 0)
    links = r.setdefault("links", {})
    for k, v in (fresh.get("links") or {}).items():
        searched = "bandcamp.com/search" in (links.get(k) or "")
        if v and (not links.get(k) or (k == "bandcamp" and searched and "bandcamp.com/search" not in v)):
            links[k] = v


def shown(r, with_callbacks):
    """A fingerprint of the card as it would be posted now, to tell whether the channel post is out of date."""
    raw = json.dumps([card.caption(r), card.buttons(r, with_callbacks=with_callbacks)], ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
