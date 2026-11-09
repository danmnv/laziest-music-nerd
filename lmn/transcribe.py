"""Transcripts, by the video itself, of archive reviews that have only Fantano's short lines on theneedledrop.com.

Most reviews before 2024 are only a video: the site has one line under it, so lmn/briefs.py could only retell that
line ("src": "short", or no brief at all: "short": "none"). The owner (2026-11-08) chose: free Gemini writes down what
Fantano says in the video, and GPT-6 Luna (lmn/briefs.py, the daily «Брифы для архива») writes the full description
from that text, as it did for the reviews with a text on the site. The transcripts stay in the private data repo
(data/transcripts/<review id>.txt), so a later change of the description's rules needs no video again.

The free tier's limits (seen 2026-11-08): no more than 8 hours of YouTube video a day for the whole project, and a daily
request limit per model. New reviews (lmn/check.py, every half hour) watch videos too, and they come first: this job
takes at most VIDEO_MINUTES of video and PER_MODEL requests on each model a day, never the model new reviews start with
(transcribe.yml), and stops for the day when every model's share is used. Any model writes a transcript well.
"""
import difflib
import json
import os
import re
from pathlib import Path

from . import briefs, gemini, tnd

DATA = Path(os.environ.get("DATA_DIR", "data"))
VIDEO_MINUTES = int(os.environ.get("VIDEO_MINUTES") or 420)  # of the 8 hours a day: the rest is for new reviews
PER_MODEL = int(os.environ.get("VIDEO_PER_MODEL") or 12)  # requests a day on each model: the rest is for new reviews
MAX_VIDEO_MIN = 30  # a longer one (a few old ones are an hour) costs a day's share: left alone
MIN_CHARS = 1000  # a shorter answer is not a whole review (a 4-minute one is ~3000 characters)
CHARS_A_MINUTE = 400  # he speaks ~150 words a minute (~800 characters): less is cut short or a summary
# Every review on the channel names it near the start ("Anthony Fantano here, the internet's busiest music nerd",
# "theneedledrop.com"; guest hosts say the channel's name): the title of the request has only artist and album
HOST = re.compile(r"fantano|needle ?drop|music nerd", re.I)
FAIL_MAX = 2  # runs in which the model answered with no usable transcript for this video: then it keeps its retelling
GIVE_UP = 3  # no answer at all this many times in a row: the key, the quota or the service is wrong today

PROMPT = """Transcribe everything the host says in this video review, word for word, in English, as plain text.
No timestamps, no speaker labels, no descriptions of sounds or music, no headings, no comments or summary of your own.
Leave out music clips; when he reads out or sings song lyrics, write only [lyrics]. Write album, song and artist names as he says them. Start a new paragraph when he moves on to
another part of the review. If you cannot hear the video, answer with nothing at all: never invent a transcript.
The video: "{title}"."""
# Asked again when the first answer was stopped for RECITATION (2026-11-09: 2 of 5 reviews from 2024, on every model,
# 0 characters): the answer matched text already on the web too closely. A close wording keeps every point for Luna.
CLOSE = """
Write it in close wording rather than character for character: drop filler words, stutters and repetitions, and keep
every point he makes, in his order."""
BLOCKED = {"PROHIBITED_CONTENT", "SAFETY", "BLOCKLIST", "SPII", "IMAGE_SAFETY"}  # the same video is refused again
watched = 0  # answered requests in the last ask(): each one watched the video


def path(review_id):
    """Whole review texts: private, like the site's own transcripts. Nothing that is published (site.py, the Worker,
    pages.yml) may read this folder."""
    return DATA / "transcripts" / f"{review_id}.txt"


def have():
    """Review ids with a transcript."""
    d = DATA / "transcripts"
    return {p.stem for p in d.glob("*.txt")} if d.is_dir() else set()


def todo(archive, data, done):
    """Archive reviews with only a retelling of Fantano's lines (or none), no transcript yet and a known video, newest
    first."""
    notes = _load("notes.json", {})
    out = []
    for a in archive:
        v = data.get(a["id"]) or {}
        if a["id"] in done or not (v.get("src") == "short" or v.get("short") == "none") or v.get("vf", 0) >= FAIL_MAX:
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


def plausible(text, mins=None):
    """A whole transcript of the review: the host's own words (a model that could not see the video may make one up from
    the title), and as long as the video's speech (not cut short, not a summary)."""
    return len(text) >= max(MIN_CHARS, CHARS_A_MINUTE * (mins or 0)) and bool(HOST.search(text))


def ask(a, api_key, mins=None, close=False):
    """("ok", text, model) | ("bad", None, model): the model answered, but no whole transcript | ("blocked", None, model):
    the video is refused, and would be again | ("none", None, None)."""
    global watched
    watched = 0 if not close else watched
    prompt = PROMPT.format(title=f"{a['artist_name']} - {a['album']}") + (CLOSE if close else "")
    body = {"contents": [{"parts": [{"fileData": {"fileUri": f"https://www.youtube.com/watch?v={a['video_id']}"}},
                                    {"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 24000, "mediaResolution": "MEDIA_RESOLUTION_LOW"}}
    model, raw = gemini.generate(body, api_key, budget=gemini.VIDEO_BUDGET_SEC, call_timeout=gemini.VIDEO_CALL_TIMEOUT)
    if raw is None:
        return ("bad", None, model) if close else ("none", None, None)  # the first answer was there: not "no answer"
    watched += 1
    cands = raw.get("candidates") if isinstance(raw, dict) else None
    if not cands:  # the request itself was refused: why, so a run's log tells
        fb = (raw.get("promptFeedback") if isinstance(raw, dict) else None) or {}
        print(f"gemini {model}: no answer, refused: {fb.get('blockReason')} {fb.get('blockReasonMessage') or ''}".rstrip())
        return ("blocked" if fb.get("blockReason") else "bad"), None, model
    cand = cands[0] if isinstance(cands[0], dict) else {}
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    if cand.get("finishReason") not in (None, "STOP"):  # cut at the token limit, blocked, or recitation: not the whole review
        flagged = [r.get("category") for r in cand.get("safetyRatings") or [] if r.get("blocked")
                   or r.get("probability") in ("MEDIUM", "HIGH")]
        print(f"gemini {model}: stopped ({cand.get('finishReason')}) after {len(text)} characters"
              + (f", flagged: {', '.join(map(str, flagged))}" if flagged else ""))
        if cand.get("finishReason") == "RECITATION" and not close:
            return ask(a, api_key, mins, close=True)
        return ("blocked" if cand.get("finishReason") in BLOCKED else "bad"), None, model
    if not plausible(text, mins):
        print(f"gemini {model}: {len(text)} characters for {mins or 0:.0f} min, host named: {bool(HOST.search(text))}")
        if len(text) < 300:  # not a transcript: a refusal or an excuse, worth seeing
            print(f"  answer: {text!r}")
        return "bad", None, model
    return "ok", text, model


def _load(name, default):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else default


def run():
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        print("no GEMINI_API_KEY: nothing to do")
        return
    if os.environ.get("TRANSCRIBE_COMPARE"):
        return compare(api_key, int(os.environ["TRANSCRIBE_COMPARE"]))
    if os.environ.get("TRANSCRIBE_PROBE"):
        return probe(api_key, re.findall(r"[0-9a-f]{24}", os.environ["TRANSCRIBE_PROBE"]))
    archive = _load("archive.json", [])
    bpath = DATA / "briefs.json"
    data = _load("briefs.json", {})
    limit = int(os.environ.get("VIDEO_LIMIT") or 0)
    items = todo(archive, data, have())
    print(f"transcripts: {len(have())} done, {len(items)} to write; today up to {VIDEO_MINUTES} min of video, "
          f"{PER_MODEL} requests a model" + (f", {limit} reviews" if limit else ""))
    left, made, failed, streak, lengths = VIDEO_MINUTES, 0, 0, 0, {}
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
        got, text, model = ask(a, api_key, mins)
        for m, k in gemini.requests.items():  # every request counts, a retry or a timed-out one too
            if k >= PER_MODEL:
                gemini._unavailable.add(m)  # its rest of the day is for new reviews
        left -= mins * max(1, watched)  # watched even with no answer: it counts against the day either way
        if got == "none":
            streak += 1
            if streak >= GIVE_UP:
                print(f"::warning::no answer {GIVE_UP} times in a row: stopping for today")
                break
            continue
        streak = 0
        if got == "ok":
            path(a["id"]).parent.mkdir(parents=True, exist_ok=True)
            path(a["id"]).write_text(text + "\n")
            made += 1
            print(f"  + {a['artist_name']} - {a['album']} ({mins:.0f} min, {len(text)} characters, {model})")
        else:
            vf = FAIL_MAX if got == "blocked" else data[a["id"]].get("vf", 0) + 1  # refused: no use asking again
            data[a["id"]] = {**data[a["id"]], "vf": vf}
            briefs.save(bpath, data)
            failed += 1
            print(f"  - {a['artist_name']} - {a['album']}: no usable transcript ({got}, {model})")
    print(f"transcripts: made {made}, unusable {failed}, {VIDEO_MINUTES - left:.0f} min of video watched")


def compare(api_key, n):
    """How close Gemini's transcript is to the site's own, on the newest n archive reviews that have a full text there.
    Saves nothing."""
    data = _load("briefs.json", {})
    full = [a for a in _load("archive.json", []) if a.get("video_id") and (data.get(a["id"]) or {}).get("brief")
            and (data.get(a["id"]) or {}).get("src") is None]
    for a in sorted(full, key=lambda a: a["published"], reverse=True)[:n]:
        a = tnd.tidy_entry(dict(a))
        site = tnd.fetch_texts([a["id"]]).get(a["id"]) or ""
        got, text, model = ask(a, api_key)
        if got != "ok":
            print(f"{a['artist_name']} - {a['album']}: {got} ({model})")
            continue
        words = lambda s: re.findall(r"[a-z0-9']+", s.lower())
        ratio = difflib.SequenceMatcher(None, words(site), words(text), autojunk=False).ratio()
        print(f"{a['artist_name']} - {a['album']} ({model}): {len(words(text))} words vs the site's {len(words(site))}, "
              f"{ratio:.0%} the same words in the same order")
        print("  Gemini:", text[:600].replace("\n", " "))
        print("  site:  ", site[:600].replace("\n", " "))


def probe(api_key, ids, models=1):
    """Why these reviews got no transcript: each one asked of the first few models in turn, with what each answered.
    Saves nothing."""
    data = _load("briefs.json", {})
    items = [a for a in todo(_load("archive.json", []), {k: {**data.get(k, {}), "vf": 0} for k in ids}, set())
             if a["id"] in ids]
    lengths = minutes([a["video_id"] for a in items]) if items else {}
    for a in items:
        mins = lengths.get(a["video_id"])
        print(f"{a['artist_name']} - {a['album']} ({a['video_id']}, {mins or 0:.0f} min)")
        for m in gemini.MODELS[:models]:
            keep = set(gemini._unavailable)
            gemini._unavailable.update(x for x in gemini.MODELS if x != m)  # this model only
            got, text, model = ask(a, api_key, mins)
            gemini._unavailable.clear()
            gemini._unavailable.update(keep)
            print(f"  {m}: {got}" + (f", {len(text)} characters: {text[:200]!r}" if text else ""))


if __name__ == "__main__":
    run()
