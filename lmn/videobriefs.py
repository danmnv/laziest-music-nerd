"""Full descriptions, by the video itself, for archive reviews that have only Fantano's short lines.

Most reviews before 2024 are only a video: theneedledrop.com has one line under it, so lmn/briefs.py could only retell
that line ("src": "short", or no brief at all: "short": "none"). The owner (2026-11-04) chose to have free Gemini watch
those videos in the background and write the full description, by the archive's rules (gemini.PROMPT_RU), in Russian
and English, over as many days as the free tier takes.

The free tier's limits (seen 2026-11-08): no more than 8 hours of YouTube video a day for the whole project, and a daily
request limit per model. New reviews (lmn/check.py, every half hour) watch videos too, and they come first: this job
takes at most VIDEO_MINUTES of video and PER_MODEL requests on each model a day (its own models, without the one new reviews
start with: videobriefs.yml), and stops for the day when every model's share is used. What it wrote replaces the retelling ("src": "video"); a review whose video gave no description in
FAIL_MAX runs keeps its retelling.
"""
import json
import os
import re
from pathlib import Path

from . import briefs, gemini, tnd

DATA = Path(os.environ.get("DATA_DIR", "data"))
VIDEO_MINUTES = int(os.environ.get("VIDEO_MINUTES") or 300)  # of the 8 hours a day: the rest is for new reviews
PER_MODEL = int(os.environ.get("VIDEO_PER_MODEL") or 12)  # requests a day on each model: the rest is for new reviews
MAX_VIDEO_MIN = 30  # a longer one (a few old ones are an hour) costs a day's share: left alone
FAIL_MAX = 2  # runs in which the model answered with no description for this video: then it keeps its retelling
GIVE_UP = 3  # no answer at all this many times in a row: the key, the quota or the service is wrong today

_SOURCE = "Ниже — текст его обзора на английском."
_TEXT = "Текст обзора:\n"
assert gemini.PROMPT_RU.count(_SOURCE) == 1 and gemini.PROMPT_RU.count(_TEXT) == 1
PROMPT = (gemini.PROMPT_RU.replace(_SOURCE, "Выше — сам его видеообзор на YouTube; ниже — его строки под видео.")
          .replace(_TEXT, "Строки под видео:\n"))


def todo(archive, data, notes):
    """Archive reviews with only a retelling of Fantano's lines (or none) and a known video, newest first."""
    out = []
    for a in archive:
        v = data.get(a["id"]) or {}
        if not (v.get("src") == "short" or v.get("short") == "none") or v.get("vf", 0) >= FAIL_MAX:
            continue
        vid = a.get("video_id") or (notes.get(a["id"]) or {}).get("video_id")
        if vid:
            out.append({**tnd.tidy_entry(dict(a)), "video_id": vid})
    return sorted(out, key=lambda a: a["published"], reverse=True)


def minutes(video_ids):
    """Each video's length in minutes, from the YouTube API (50 a request); a video it doesn't return is left out."""
    from .yt_archive import yt
    out = {}
    for i in range(0, len(video_ids), 50):
        d = yt("videos", part="contentDetails", id=",".join(video_ids[i:i + 50]))
        for it in d.get("items", []):
            m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", it["contentDetails"].get("duration") or "")
            if m:
                dd, h, mi, s = (int(x or 0) for x in m.groups())
                out[it["id"]] = dd * 1440 + h * 60 + mi + s / 60
    return out


def lines(a, note):
    """What he wrote under the video (data/notes.json): his blurb and favourite tracks."""
    note = note or {}
    out = [note.get("blurb") or ""]
    fav = [f.get("t") for f in note.get("fav") or [] if isinstance(f, dict) and f.get("t")]
    if fav:
        out.append("FAV TRACKS: " + ", ".join(fav))
    return "\n".join(x for x in out if x).strip() or "(нет)"


def ask(a, note, api_key):
    """("ok", answer) | ("bad", None): the model answered, but no description | ("none", None): no answer."""
    tags = briefs.tags(a)
    text = PROMPT.format(title=f"{a['artist_name']} - {a['album']}", text=lines(a, note), verdict=briefs.verdict(a),
                         en=gemini.EN_FIELD, tags=f"Теги: {', '.join(tags)}.\n" if tags else "",
                         moods=json.dumps(gemini.AI_MOODS, ensure_ascii=False))
    body = {"contents": [{"parts": [{"fileData": {"fileUri": f"https://www.youtube.com/watch?v={a['video_id']}"}}, {"text": text}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4, "mediaResolution": "MEDIA_RESOLUTION_LOW"}}
    model, raw = gemini.generate(body, api_key, budget=gemini.VIDEO_BUDGET_SEC, call_timeout=gemini.VIDEO_CALL_TIMEOUT)
    if raw is None:
        return "none", None
    try:
        out = gemini.parse_answer(raw["candidates"][0]["content"]["parts"][0]["text"])
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
        print(f"gemini {model}: bad response {e!r}")
        return "bad", {"model": model}
    out["model"] = model
    return ("ok" if out.get("brief") else "bad"), out


def run():
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        print("no GEMINI_API_KEY: nothing to do")
        return
    archive = json.loads((DATA / "archive.json").read_text())
    path = DATA / "briefs.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    notes = json.loads((DATA / "notes.json").read_text()) if (DATA / "notes.json").exists() else {}
    limit = int(os.environ.get("VIDEO_LIMIT") or 0)
    items = todo(archive, data, notes)
    print(f"video briefs: {len(items)} to write; today up to {VIDEO_MINUTES} min of video, {PER_MODEL} requests a model"
          + (f", {limit} reviews" if limit else ""))
    left, made, failed, streak = VIDEO_MINUTES, 0, 0, 0
    lengths = {}
    for n, a in enumerate(items):
        if limit and made + failed >= limit:
            break
        if n % 50 == 0:  # the next 50 videos' lengths, in one request
            try:
                lengths = minutes([x["video_id"] for x in items[n:n + 50]])
            except Exception as e:  # without the lengths the day's share can't be kept: stop
                print(f"::warning::YouTube API: {e}; stopping")
                break
        mins = lengths.get(a["video_id"])
        if mins is None or mins > MAX_VIDEO_MIN:
            continue  # gone, private, or too long: its retelling stays
        if mins > left:
            print(f"today's {VIDEO_MINUTES} min of video used up")
            break
        if all(m in gemini._unavailable for m in gemini.MODELS):
            print("every model's share for today is used up")
            break
        got, out = ask(a, notes.get(a["id"]), api_key)
        model = (out or {}).get("model")
        for m, n in gemini.requests.items():  # every request counts, a retry or a timed-out one too
            if n >= PER_MODEL:
                gemini._unavailable.add(m)  # its rest of the day is for new reviews
        left -= mins  # the video may have been watched even with no answer: it counts against the day either way
        if got == "none":
            streak += 1
            if streak >= GIVE_UP:
                print(f"::warning::no answer {GIVE_UP} times in a row: stopping for today")
                break
            continue
        streak = 0
        if got == "ok":
            data[a["id"]] = {**briefs.entry(out, "both"), "src": "video"}
            made += 1
            print(f"  + {a['artist_name']} - {a['album']} ({mins:.0f} min, {model})")
        else:
            data[a["id"]] = {**data[a["id"]], "vf": data[a["id"]].get("vf", 0) + 1}
            failed += 1
            print(f"  - {a['artist_name']} - {a['album']}: no description ({model})")
        briefs.save(path, data)  # after each one: a stopped job keeps what it wrote
    briefs.save(path, data)
    print(f"video briefs: made {made}, no description {failed}, {VIDEO_MINUTES - left:.0f} min of video watched")


if __name__ == "__main__":
    run()
