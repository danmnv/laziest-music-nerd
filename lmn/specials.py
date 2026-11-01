"""Fantano's special videos: "Artist: Worst to Best" rankings and the year/decade lists.

- Lists ("Top 50 Albums of 2017", "Top 15 EPs of 2019", "15 Worst Albums of the 2010s", ...): the video description lists
  every album as "Artist - Album", alphabetically, so membership is exact; places are only in the video.
- Rankings ("Radiohead: Worst to Best", 9 videos up to 2025): the order is only in the video. Gemini watches it, and the
  answer counts only when a numbered list in the comments has the same albums in the same order ("verified"). Unverified
  rankings are kept for the record but not shown as places.

Gemini quota is shared with the briefs for new reviews (free tier: requests per day per model), so this uses at most
SPECIALS_GEMINI_CALLS calls per run, on the models the workflow names (not the briefs' first choice).

Writes data/specials.json. Run: python -m lmn.specials (workflow «Особые видео Фантано»)."""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import gemini, notes
from .musicbrainz import norm
from .tnd import tidy_entry

DATA = Path(os.environ.get("DATA_DIR", "data"))
RETRY = timedelta(days=7)  # an unverified ranking is asked again after a week (comments grow, models change)
WTB = re.compile(r"^\s*(?P<artist>.+?)\s*:\s*worst\s+to\s+best\s*$", re.I)
NUMBERED = re.compile(r"^\s*#?(\d{1,2})\s*[.):\-]\s*(.+?)\s*$")


def list_kind(title):
    """Russian label of a list video, or None. Mid-year "so far" lists of one year are left out: the year list replaces them."""
    t = re.sub(r"\s+", " ", title or "").strip()
    m = re.match(r"^(?:top )?(\d+) (?:best )?(albums|eps) of (20\d\d)$", t, re.I)
    if m:
        what = "альбомов" if m.group(2).lower() == "albums" else "EP"
        return f"топ-{m.group(1)} {what} {m.group(3)} года"
    m = re.match(r"^(?:top )?(\d+) worst albums of (?:the )?(20\d\d)(s?)$", t, re.I)
    if m:
        return f"{m.group(1)} худших альбомов " + (f"{m.group(2)}-х" if m.group(3) else f"{m.group(2)} года")
    m = re.match(r"^top (\d+) albums of the (20\d0)s$", t, re.I)
    if m:  # the description holds only the top 100 ("The top 100, sorted by artist"); 101-200 are on a site page
        return f"топ-100 альбомов {m.group(2)}-х"
    m = re.match(r"^best albums of the (20\d0)s so far$", t, re.I)
    if m:
        return f"лучшие альбомы {m.group(1)}-х (промежуточный список)"
    return None


def parse_list(desc):
    """[(artist, album)] from a list video's description, up to the editors' lists and the channel links."""
    out = []
    for line in (desc or "").split("\n"):
        line = line.strip()
        if line.startswith("====") or re.search(r"editor lists|'s list:|wouldn't fit", line, re.I):
            break
        if "http" in line or len(line) > 160:
            continue
        m = re.match(r"^(.+?)\s*[-–]\s+(.+)$", line)
        if m and not line.endswith(":"):
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


def _album_key(album, artist):
    a = re.sub(r"\s*[(\[][^)\]]*[)\]]\s*$", "", album or "")  # "10,000 gecs (sorry for saying 1000 in vid)"
    k = norm(a)
    return norm(artist) if k in ("selftitled", "st") else k


def archive_index(archive):
    idx = {}
    for a in archive:
        if a.get("artist_name") and a.get("album") and not a.get("guest"):
            idx.setdefault((norm(a["artist_name"]), _album_key(a["album"], a["artist_name"])), a["id"])
    return idx


def find_review(idx, artist, album):
    return idx.get((norm(artist), _album_key(album, artist)))


def _same(a, b):
    a, b = norm(a), norm(b)
    return bool(a and b) and (a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a)))


def verify(order, comments):
    """True when some comment numbers the same albums in the same order (either direction): Gemini's answer checked
    against what people who watched the video wrote. order: album titles, worst first."""
    need = max(4, int(len(order) * 0.8 + 0.999))
    for text in comments:
        seq = []
        for line in (text or "").split("\n"):
            m = NUMBERED.match(line)
            if not m:
                continue
            hit = next((i for i, o in enumerate(order) if _same(o, m.group(2))), None)
            if hit is not None and hit not in seq:
                seq.append(hit)
        if len(seq) >= need and (seq == sorted(seq) or seq == sorted(seq, reverse=True)):
            return True
    return False


def ask_gemini(video_id, artist, api_key):
    prompt = (f"This is Anthony Fantano's video ranking {artist}'s albums from worst to best. List the albums in the exact "
              "order he ranks them, from worst to best, with the timestamp where each one is introduced. Answer as JSON: "
              '{"ranking": [{"place_from_worst": 1, "album": "...", "time": "mm:ss"}]}')
    body = {"contents": [{"parts": [{"fileData": {"fileUri": f"https://www.youtube.com/watch?v={video_id}"}}, {"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0, "mediaResolution": "MEDIA_RESOLUTION_LOW"}}
    model, raw = gemini.generate(body, api_key, budget=600)
    if raw is None:
        return None
    try:
        rows = json.loads(raw["candidates"][0]["content"]["parts"][0]["text"])["ranking"]
        rows = sorted(rows, key=lambda r: int(r["place_from_worst"]))
        return [{"album": str(r["album"]).strip(), "t": _seconds(r.get("time"))} for r in rows if str(r.get("album", "")).strip()]
    except (KeyError, IndexError, TypeError, ValueError) as e:
        print(f"  ! gemini {model}: bad answer {e!r}", file=sys.stderr)
        return None


def _seconds(t):
    m = re.match(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$", str(t or "").strip())
    return (int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))) if m else None


def comments(video_id, yt):
    out, token = [], None
    for _ in range(3):
        d = yt("commentThreads", part="snippet", videoId=video_id, maxResults=100, order="relevance", textFormat="plainText",
               **({"pageToken": token} if token else {}))
        out += [it["snippet"]["topLevelComment"]["snippet"]["textDisplay"] for it in d.get("items", [])]
        token = d.get("nextPageToken")
        if not token:
            break
    return out


def run():
    from .yt_archive import all_uploads, yt  # needs YOUTUBE_API_KEY
    now = datetime.now(timezone.utc)
    path = DATA / "specials.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    archive = [tidy_entry(a) for a in json.loads((DATA / "archive.json").read_text())]
    idx = archive_index(archive)
    ups = all_uploads()
    npath = DATA / "notes.json"
    old_notes = json.loads(npath.read_text()) if npath.exists() else {}
    # no new lookups after 22 minutes: the step's limit is 40, and up to 3 Gemini videos (~4 min each) come after
    deadline = time.monotonic() + 60 * float(os.environ.get("LOOKUP_MINUTES", "22"))
    nt = notes.build(ups, archive, old_notes, int(os.environ.get("NOTES_DEEZER_LIMIT", "1500")),
                     int(os.environ.get("NOTES_APPLE_LIMIT", "200")), deadline)
    npath.write_text("{\n" + ",\n".join(json.dumps(k) + ": " + json.dumps(nt[k], ensure_ascii=False, separators=(",", ":"))
                                          for k in sorted(nt)) + "\n}\n")
    cpath = DATA / "covers.json"
    cv = notes.covers(archive, json.loads(cpath.read_text()) if cpath.exists() else {}, int(os.environ.get("COVERS_LIMIT", "1500")), deadline)
    cpath.write_text("{\n" + ",\n".join(json.dumps(k) + ": " + json.dumps(cv[k]) for k in sorted(cv)) + "\n}\n")
    lists = []
    for u in ups:
        label = list_kind(u["title"])
        if not label:
            continue
        items = [{"artist": ar, "album": al, "review": find_review(idx, ar, al)} for ar, al in parse_list(u["desc"])]
        if items:
            lists.append({"video_id": u["id"], "title": u["title"].strip(), "date": u["date"][:10], "label": label, "items": items})
            print(f"list {u['date'][:10]} {u['title'].strip()}: {len(items)} albums, {sum(1 for i in items if i['review'])} matched")
    calls = int(os.environ.get("SPECIALS_GEMINI_CALLS", "3"))
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    prev = {r["video_id"]: r for r in old.get("rankings", [])}
    rankings = []
    for u in sorted(ups, key=lambda u: u["date"]):
        m = WTB.match(u["title"])
        if not m:
            continue
        artist = m.group("artist")
        r = prev.get(u["id"]) or {"video_id": u["id"], "title": u["title"].strip(), "artist": artist, "date": u["date"][:10],
                                  "verified": False, "items": []}
        fresh = not r.get("checked") or now - datetime.fromisoformat(r["checked"]) >= RETRY
        if not r["verified"] and fresh and calls > 0 and key:
            calls -= 1
            order = ask_gemini(u["id"], artist, key)
            r["checked"] = now.isoformat(timespec="seconds")
            if order:
                try:
                    cs = comments(u["id"], yt)
                except Exception as e:  # comments turned off (403), quota, 5xx: keep the answer unverified, don't lose the run
                    print(f"  ! comments {u['id']}: {e}", file=sys.stderr)
                    cs = []
                ok = verify([o["album"] for o in order], cs)
                n = len(order)
                r["verified"] = ok
                r["items"] = [{"album": o["album"], "place": n - i, "t": o["t"], "review": find_review(idx, artist, o["album"])}
                              for i, o in enumerate(order)]
        print(f"ranking {r['date']} {r['title']}: {len(r['items'])} albums, verified={r['verified']}")
        rankings.append(r)
        save(path, lists, rankings + [x for x in prev.values() if x["video_id"] not in {y["video_id"] for y in rankings}])
    save(path, lists, rankings)


def save(path, lists, rankings):
    # after each ranking too: a crash or timeout later in the run keeps the Gemini answers already paid for
    path.write_text(json.dumps({"lists": lists, "rankings": rankings}, ensure_ascii=False, indent=0) + "\n")


def badges(specials):
    """{review id: [{"text", "url"}]}: the lists and verified ranking places each review is in, for the site and the bot."""
    out = {}
    for r in specials.get("rankings", []):
        if not r.get("verified"):
            continue
        n = len(r["items"])
        for it in r["items"]:
            if it.get("review"):
                out.setdefault(it["review"], []).append({
                    "text": f"№{it['place']} из {n} в «{r['artist']}: от худшего к лучшему» ({r['date'][:4]})",
                    "url": f"https://youtu.be/{r['video_id']}"})
    for li in specials.get("lists", []):
        for it in li["items"]:
            if it.get("review"):
                out.setdefault(it["review"], []).append({"text": li["label"], "url": f"https://youtu.be/{li['video_id']}"})
    return out


if __name__ == "__main__":
    run()
