"""Fill missing archive scores (mostly 2010-2014) from The Needle Drop's YouTube video descriptions.

Run by hand: Actions → «Архив оценок из YouTube». Needs YOUTUBE_API_KEY. Costs ~1 quota unit per 50 videos.
"""
import json
import os
import re
import urllib.parse
from pathlib import Path

from . import http
from .musicbrainz import norm

DATA = Path(os.environ.get("DATA_DIR", "data"))
API = "https://www.googleapis.com/youtube/v3"
SCORE = re.compile(r"(?<![\d.])(10|[0-9])\s*/\s*10\b")


def yt(path, **params):
    params["key"] = os.environ["YOUTUBE_API_KEY"].strip()
    try:
        return http.get_json(f"{API}/{path}?{urllib.parse.urlencode(params)}")
    except http.HttpError as e:
        raise RuntimeError(f"YouTube API {path}: HTTP {e.status}") from None  # never print the URL: it has the key


def all_uploads():
    ch = yt("channels", part="contentDetails", forHandle="@theneedledrop")
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    token, out = None, []
    while True:
        d = yt("playlistItems", part="snippet", playlistId=uploads, maxResults=50, **({"pageToken": token} if token else {}))
        for it in d["items"]:
            sn = it["snippet"]
            out.append({"id": sn["resourceId"]["videoId"], "title": sn["title"], "desc": sn.get("description", ""), "date": sn["publishedAt"]})
        token = d.get("nextPageToken")
        if not token:
            return out


def verdict(desc):
    m = list(SCORE.finditer(desc))
    if m:
        return {"score": int(m[-1].group(1))}
    if re.search(r"\bNOT GOOD\b", desc):
        return {"not_good": True}
    if re.search(r"\bCLASSIC/10\b|\bCLASSIC\b", desc):
        return {"classic": True}
    return {}


def key(artist, album):
    return norm(artist) + "|" + norm(album)


def main():
    archive = json.loads((DATA / "archive.json").read_text())
    missing = {key(a["artist_name"], a["album"]): a for a in archive
               if a.get("artist_name") and a.get("album") and a.get("score") is None and not a.get("not_good") and not a.get("classic")}
    print(f"archive entries without a score: {len(missing)}")
    videos = all_uploads()
    print(f"videos on the channel: {len(videos)}")
    filled = 0
    for v in videos:
        t = re.sub(r"\s*[-–(\[]?\s*(ALBUM|EP|MIXTAPE|TRACK)?\s*REVIEW[)\]]?\s*$", "", v["title"], flags=re.I)
        m = re.match(r"^(.+?)\s+[-–]\s+(.+)$", t)
        if not m:
            continue
        a = missing.get(key(m.group(1), m.group(2)))
        if not a:
            continue
        vd = verdict(v["desc"])
        if vd:
            a.update(vd)
            a["score_source"] = "youtube"
            a.setdefault("video_id", v["id"])
            filled += 1
    print(f"filled from YouTube: {filled}")
    (DATA / "archive.json").write_text(json.dumps(archive, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
