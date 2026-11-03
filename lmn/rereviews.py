"""Two reviews of one album in the archive (lmn/notes.py apply_dates runs this on a fresh archive.json each week):

- Fantano reviewed it again later («The Life of Pablo» 6/10 in 2016, «The Life of Pablo (Redux)» 8/10 in 2018). The
  later review is the current score, and its card names the first one; the first one's card names the later one
  (the owner, 2026-11-03). Fields: "first" on the later review, "redo" on the earlier, each {"id", "y", "score",
  "not_good", "classic"}.
- theneedledrop.com posted the same review twice, days apart ("…-2" in the address; 18 such pairs as of 2026-11-03).
  The second post gets "dup_of": the first's id, and the bot and the site leave it out.
"""
import re
from datetime import datetime

DUP_DAYS = 7  # closer than this, it is the same review posted twice; further apart, a review written again
REDUX = re.compile(r"\s*[\(\[]?\b(redux|revisited|re-?review)\b[\)\]]?\s*$", re.I)
# album titles that end in "Redux" themselves, not a second review (Vektor's album is called "Terminal Redux")
OWN_NAME = {"terminalredux"}


def _key(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def album_key(album):
    if _key(album) in OWN_NAME:
        return _key(album)
    return _key(REDUX.sub("", album or ""))


def _ts(iso):
    return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))


def _ref(a):
    return {"id": a["id"], "y": str(a["published"])[:4], "score": a.get("score"),
            "not_good": bool(a.get("not_good")), "classic": bool(a.get("classic"))}


def link(archive):
    """Set "first" / "redo" / "dup_of" on the archive's entries (in place; stale ones removed). Returns how many
    entries changed."""
    before = {a["id"]: (a.get("first"), a.get("redo"), a.get("dup_of")) for a in archive}
    for a in archive:
        for k in ("first", "redo", "dup_of"):
            a.pop(k, None)
    groups = {}
    for a in archive:
        if a.get("artist_name") and a.get("album") and not a.get("track") and a.get("published"):
            groups.setdefault((_key(a["artist_name"]), album_key(a["album"])), []).append(a)
    for items in groups.values():
        if len(items) < 2:
            continue
        items.sort(key=lambda a: (_ts(a["published"]), a["id"]))
        kept = [items[0]]
        for a in items[1:]:
            if (_ts(a["published"]) - _ts(kept[-1]["published"])).days < DUP_DAYS:
                a["dup_of"] = kept[-1]["id"]
            else:
                kept.append(a)
        for old, new in zip(kept, kept[1:]):
            new["first"] = _ref(old)
            old["redo"] = _ref(new)
    return sum(1 for a in archive if before.get(a["id"]) != (a.get("first"), a.get("redo"), a.get("dup_of")))
