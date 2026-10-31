"""Temporary probe: how far theneedledrop.com lags behind YouTube, what review descriptions hold, and Gemini on a video."""
import json
import re
from datetime import datetime

from . import gemini, tnd
from .yt_archive import yt

REVIEW = re.compile(r"(ALBUM|EP|MIXTAPE)\s+REVIEW\s*$|\bis (NOT GOOD|BAD|NOT BAD)\b|REVIEW\]?\s*$", re.I)


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


site = {}
for page in (1, 2):
    for p in tnd.fetch_posts(limit=50, page=page, with_text=True)["posts"]:
        r = tnd.parse_post(p)
        if r.get("video_id"):
            site[r["video_id"]] = r
print(f"site posts with video: {len(site)}; oldest {min(r['published'] for r in site.values())}")

ch = yt("channels", part="contentDetails", forHandle="@theneedledrop")
uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
vids, token = [], None
for _ in range(3):
    d = yt("playlistItems", part="snippet,contentDetails", playlistId=uploads, maxResults=50, **({"pageToken": token} if token else {}))
    vids += d["items"]
    token = d.get("nextPageToken")
oldest_site = min(ts(r["published"]) for r in site.values())
lags, missing, shown = [], [], 0
for it in vids:
    sn, vid = it["snippet"], it["contentDetails"]["videoId"]
    when = ts(it["contentDetails"].get("videoPublishedAt") or sn["publishedAt"])
    if when < oldest_site:
        continue
    is_review = bool(REVIEW.search(sn["title"]))
    s = site.get(vid)
    lag = (ts(s["published"]) - when).total_seconds() / 3600 if s else None
    print(f"{when:%m-%d %H:%M} {'REV ' if is_review else '    '}{'site +%.1fh' % lag if s else 'NOT ON SITE':>14}  {sn['title'][:80]}")
    if s:
        lags.append(lag)
    elif is_review:
        missing.append(sn["title"])
    tail = [l.strip() for l in sn.get("description", "").splitlines() if l.strip()][-5:]
    if "/10" in " ".join(tail) or is_review:
        print("      tail: " + " | ".join(tail)[:300])
lags.sort()
if lags:
    print(f"lag hours: n={len(lags)} min={lags[0]:.1f} median={lags[len(lags)//2]:.1f} max={lags[-1]:.1f}")
print(f"review videos not on site: {len(missing)}: {missing}")

hm = None
if hm:
    vid = hm["contentDetails"]["videoId"]
    body = {"contents": [{"parts": [{"fileData": {"fileUri": f"https://www.youtube.com/watch?v={vid}"}},
                                    {"text": "Это видеообзор альбома. Ответь JSON: {\"brief\": 1-2 предложения на русском, что Фантано думает об альбоме, \"best_tracks\": [...], \"score\": оценка из видео}"}]}],
            "generationConfig": {"responseMimeType": "application/json", "mediaResolution": "MEDIA_RESOLUTION_LOW"}}
    model, d = gemini.generate(body, gemini.os.environ["GEMINI_API_KEY"].strip(), budget=200)
    if d:
        print("gemini on video:", model, json.dumps(d.get("usageMetadata"), ensure_ascii=False))
        print(d["candidates"][0]["content"]["parts"][0]["text"][:800])
