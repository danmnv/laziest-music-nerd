"""Transcripts, by the video itself, of archive reviews that have only Fantano's short lines on theneedledrop.com.

Most reviews before 2024 are only a video: the site has one line under it, so lmn/briefs.py could only retell that
line ("src": "short", or no brief at all: "short": "none"). The owner (2026-11-08) chose: free Gemini writes down what
Fantano says in the video, and GPT-6 Luna (lmn/briefs.py, the daily «Брифы для архива») writes the full description
from that text, as it did for the reviews with a text on the site. The transcripts stay in the private data repo
(data/transcripts/<review id>.txt), so a later change of the description's rules needs no video again.

The free tier allows 8 hours of YouTube video a day. In Actions this job uses the archive's Gemini project,
separate from the new-review pipeline. Scheduled passes share a daily reservation that includes retries and fallbacks.
"""
import difflib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path

from . import briefs, decade_tens, gemini, notes, tnd, transcribe_quota

DATA = Path(os.environ.get("DATA_DIR", "data"))
VIDEO_MINUTES = int(os.environ.get("VIDEO_MINUTES") or 360)
PER_MODEL = int(os.environ.get("VIDEO_PER_MODEL") or 12)
PER_LITE_MODEL = int(os.environ["VIDEO_PER_LITE_MODEL"]) if os.environ.get("VIDEO_PER_LITE_MODEL") else None
RETELL_MODEL = os.environ.get("TRANSCRIBE_RETELL_MODEL") or ""
PER_RETELL_MODEL = int(os.environ.get("VIDEO_PER_RETELL_MODEL") or 4)
RUN_MINUTES = 90
REQUEST_GAP_SEC = 30
ARCHIVE_CALL_TIMEOUT = 180
ARCHIVE_REVIEW_BUDGET = 360
MAX_VIDEO_MIN = 30  # a longer one (a few old ones are an hour) costs a day's share: left alone
MIN_CHARS = 1000  # a shorter answer is not a whole review (a 4-minute one is ~3000 characters)
CHARS_A_MINUTE = 400  # he speaks ~150 words a minute (~800 characters): less is cut short or a summary
# Every review on the channel names it near the start ("Anthony Fantano here, the internet's busiest music nerd",
# "theneedledrop.com"; guest hosts say the channel's name): the title of the request has only artist and album
HOST = re.compile(r"fantano|needle ?drop|music nerd", re.I)
FAIL_MAX = 2  # runs in which the model answered with no usable transcript for this video: then it keeps its retelling
GIVE_UP = 3  # no answer at all this many times in a row: the key, the quota or the service is wrong today
# A video the request itself is refused for (promptFeedback.blockReason: about the input, 2026-11-09/10 Moor Mother on
# all 4 models) is not asked again. An answer stopped for one of REFUSED (RECITATION nearly always) is not asked word for
# word again either ("vr": the model, "vf": FAIL_MAX): another model rescued only 3 of 18 such videos (2026-11-10/12),
# so it goes to the retelling (RETELL) instead.
# RECITATION is Google's filter on the answer (text too close to one it knows), and a word-for-word transcript is just
# that. A video a model refused is asked, on a later run, for a close retelling of what he says instead, not word for
# word ("vt": the runs that got none). Probe 2026-11-12 on three refused videos: 9 of 9 answers were retellings, the
# same details and score from every model; on by default since (owner, 2026-11-13). TRANSCRIBE_RETELL=false: off.
RETELL = os.environ.get("TRANSCRIBE_RETELL", "").lower() not in ("0", "false")
RETOLD = "[A retelling of the review, not word for word]"  # the file's first line: lmn/briefs.py reads it as a transcript
RETELL_MIN = 800  # characters: a retelling of a 5-minute review is ~2000
REFUSED = {"RECITATION", "PROHIBITED_CONTENT", "SAFETY", "BLOCKLIST", "SPII", "IMAGE_SAFETY"}

PROMPT = """Transcribe everything the host says in this video review, word for word, in English, as plain text.
No timestamps, no speaker labels, no descriptions of sounds or music, no headings, no comments or summary of your own.
Leave out music clips. Write album, song and artist names as he says them. Start a new paragraph when he moves on to
another part of the review. If you cannot hear the video, answer with nothing at all: never invent a transcript.
The video: "{title}".{tracks}"""

PROMPT_RETELL = """Retell in English, in your own words and in detail, what the host says in this video review, in the order
he says it: how the record sounds (production, vocals, mood), every song he names and what he says about it, what he
praises, what he criticises, and his conclusion. Do not quote him and do not transcribe him word for word. No headings,
no lists, no timestamps, no opinions of your own, nothing he does not say. Leave out music clips. If you cannot hear
the video, answer with nothing at all: never invent a retelling.
The video: "{title}".{tracks}"""
TRACKS = "\nThe release's track titles, for spelling them when he names one: {}."


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
    albums = _load("albums.json", {})
    out = []
    for a in archive:
        v = data.get(a["id"]) or {}
        if a["id"] in done or not (v.get("src") == "short" or v.get("short") == "none"):
            continue
        retell = v.get("vf", 0) >= FAIL_MAX
        if retell and not (RETELL and v.get("vr") and v.get("vt", 0) < FAIL_MAX):  # only what models refused (RECITATION
            continue  # and the like), not a request refused for the video itself (blocked: no "vr")
        vid = a.get("video_id") or (notes.get(a["id"]) or {}).get("video_id")
        if vid:
            out.append({**tnd.tidy_entry(dict(a)), "video_id": vid, **({"retell": True} if retell else {}),
                        "tracks": briefs.tracklist(albums, a["id"])})
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


def plausible_retelling(text):
    """A retelling: long enough to hold the review, and not a refusal or an excuse. Whether it is made up from the
    title can't be told from the text: a probe's retellings are read by a person first (RETELL is off until then)."""
    return len(text) >= RETELL_MIN and not re.match(r"(i'?m sorry|i cannot|i can't|unfortunately)", text, re.I)


class RunBudget:
    def __init__(self, reservation=None, seconds_to_reset=None):
        self.minutes = VIDEO_MINUTES if reservation is None else reservation["minutes"]
        self.minutes_left = self.minutes
        self.limits = None if reservation is None else reservation["requests"]
        seconds = 60 * RUN_MINUTES
        if seconds_to_reset is not None:
            seconds = min(seconds, seconds_to_reset)
        self.deadline = time.monotonic() + seconds
        self.next_request = 0

    def model_limit(self, model):
        if self.limits is not None:
            return self.limits.get(model, 0)
        if model == RETELL_MODEL:
            return PER_RETELL_MODEL
        if PER_LITE_MODEL is not None and model.endswith("-flash-lite"):
            return PER_LITE_MODEL
        return PER_MODEL

    def model_spent(self, model):
        return gemini.requests.get(model, 0) >= self.model_limit(model)

    def reserve(self, minutes, model, deadline):
        if self.minutes_left < minutes or self.model_spent(model):
            return False
        now = time.monotonic()
        delay = max(0, self.next_request - now)
        latest = min(deadline, self.deadline) - gemini.MIN_REQUEST_SEC
        if now + delay >= latest:
            return False
        if delay:
            time.sleep(delay)
        now = time.monotonic()
        if now >= latest:
            return False
        self.next_request = now + REQUEST_GAP_SEC
        self.minutes_left -= minutes
        return True


def ask(a, api_key, mins=None, retell=False, run_budget=None, model_order=None):
    """("ok", text, model) | ("bad", None, model): the model answered, but no whole transcript | ("blocked", None, model):
    the request was refused (the video itself) | ("refused", None, model): this model stopped its answer (REFUSED) |
    ("none", None, None)."""
    body = {"contents": [{"parts": [{"fileData": {"fileUri": f"https://www.youtube.com/watch?v={a['video_id']}"}},
                                    {"text": (PROMPT_RETELL if retell else PROMPT).format(
                                        title=f"{a['artist_name']} - {a['album']}",
                                        tracks=TRACKS.format("; ".join(a["tracks"])) if a.get("tracks") else "")}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 24000, "mediaResolution": "MEDIA_RESOLUTION_LOW"}}
    if run_budget is None:
        model, raw = gemini.generate(body, api_key, budget=gemini.VIDEO_BUDGET_SEC, call_timeout=gemini.VIDEO_CALL_TIMEOUT)
    else:
        model, raw = gemini.generate(
            body, api_key,
            budget=min(ARCHIVE_REVIEW_BUDGET, run_budget.deadline - time.monotonic()),
            call_timeout=ARCHIVE_CALL_TIMEOUT,
            before_request=partial(run_budget.reserve, mins),
            model_order=model_order,
        )
    if raw is None:
        return "none", None, None
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
        return ("refused" if cand.get("finishReason") in REFUSED else "bad"), None, model
    if retell:
        if not plausible_retelling(text):
            print(f"gemini {model}: a retelling of {len(text)} characters: {text[:200]!r}")
            return "bad", None, model
        return "ok", f"{RETOLD}\n\n{text}", model
    if not plausible(text, mins):
        print(f"gemini {model}: {len(text)} characters for {mins or 0:.0f} min, host named: {bool(HOST.search(text))}")
        if len(text) < 300:  # not a transcript: a refusal or an excuse, worth seeing
            print(f"  answer: {text!r}")
        return "bad", None, model
    return "ok", text, model


def _load(name, default):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else default


def claim_quota():
    budget = RunBudget()
    main = {model: budget.model_limit(model) for model in gemini.MODELS}
    late = {model: 1 if model == RETELL_MODEL else 8
            for model in main if model == RETELL_MODEL or model.endswith("-flash-lite")}
    transcribe_quota.claim(
        DATA / transcribe_quota.FILENAME, os.environ["TRANSCRIBE_QUOTA_SLOT"], os.environ["TRANSCRIBE_QUOTA_OWNER"],
        budget.minutes, main, late, datetime.now(timezone.utc),
    )


def process_decade_tens(archive, api_key, run_budget, limit):
    """Use the archive's existing request and video-duration budget before ordinary reviews."""
    path = DATA / decade_tens.FILENAME
    cached = _load(decade_tens.FILENAME, {})
    videos = cached.setdefault("videos", {})
    now = datetime.now(timezone.utc)
    pending = [vid for vid in decade_tens.EPISODES if not videos.get(vid, {}).get("items")
               and videos.get(vid, {}).get("retry_after", "") <= now.isoformat()]
    tried = 0
    if pending:
        try:
            lengths = minutes(pending)
        except Exception as e:
            print(f"::warning::These Albums Are 10s: YouTube API: {e}")
            lengths = {}
        for vid in pending:
            if limit and tried >= limit:
                break
            mins = lengths.get(vid)
            if not mins or mins > run_budget.minutes_left:
                continue
            before = sum(gemini.requests.values())
            result = decade_tens.request(
                vid, api_key, mins,
                budget=min(ARCHIVE_REVIEW_BUDGET, run_budget.deadline - time.monotonic()),
                call_timeout=ARCHIVE_CALL_TIMEOUT,
                before_request=partial(run_budget.reserve, mins),
            )
            if sum(gemini.requests.values()) == before:
                continue
            tried += 1
            if result:
                videos[vid] = result
                print(f"These Albums Are 10s {vid}: {len(result['items'])} album descriptions")
            else:
                videos[vid] = {"retry_after": (now + timedelta(days=1)).isoformat()}
                print(f"::warning::These Albums Are 10s {vid}: no usable answer, will retry")
            decade_tens.save(path, cached)

    if not videos:
        return tried

    # Fill covers and tracklists before the weekly album job reaches these 2022 entries. It can refine them later.
    regular = _load("albums.json", {})
    cached_albums = cached.get("albums", {})
    items = [{**a, "id": key} for _, _, key, a in decade_tens.series_albums(archive) if not notes.found(regular.get(a["id"]))]
    if items:
        albums = notes.albums(items, cached_albums, limit=len(items),
                              deadline=min(run_budget.deadline, time.monotonic() + 120))
        if albums != cached_albums:
            cached["albums"] = albums
            decade_tens.save(path, cached)
    return tried


def run():
    api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        print("no GEMINI_API_KEY: nothing to do")
        return
    if os.environ.get("TRANSCRIBE_COMPARE"):
        return compare(api_key, int(os.environ["TRANSCRIBE_COMPARE"]))
    if os.environ.get("TRANSCRIBE_CARDS"):
        return cards(api_key, os.environ["TRANSCRIBE_CARDS"].strip())
    if os.environ.get("TRANSCRIBE_PROBE"):
        return probe(api_key, re.findall(r"[0-9a-f]{24}", os.environ["TRANSCRIBE_PROBE"]))
    slot = os.environ.get("TRANSCRIBE_QUOTA_SLOT")
    quota_path = DATA / transcribe_quota.FILENAME
    if slot:
        now = datetime.now(timezone.utc)
        claim = transcribe_quota.reservation(quota_path, slot, os.environ["TRANSCRIBE_QUOTA_OWNER"], now)
        if claim is None:
            print("transcripts: no active reservation for this pass")
            return
        state, reservation, reset = claim
        run_budget = RunBudget(reservation, (reset - now).total_seconds())
    else:
        run_budget = RunBudget()
    archive = _load("archive.json", [])
    bpath = DATA / "briefs.json"
    data = _load("briefs.json", {})
    limit = int(os.environ.get("VIDEO_LIMIT") or 0)
    special_tried = process_decade_tens(archive, api_key, run_budget, limit)
    items = todo(archive, data, have())
    if slot == "late" and run_budget.model_limit(RETELL_MODEL):
        retelling = next((i for i, item in enumerate(items) if item.get("retell")), None)
        if retelling is not None:
            items.insert(0, items.pop(retelling))
    limits = {model: run_budget.model_limit(model) for model in gemini.MODELS}
    print(f"transcripts: {len(have())} done, {len(items)} to write; up to {run_budget.minutes:g} min of video, "
          f"HTTP request limits: {limits}" + (f", {limit} reviews" if limit else ""))
    made, failed, streak, lengths = 0, 0, 0, {}
    for n, a in enumerate(items):
        if limit and special_tried + made + failed >= limit:
            break
        if time.monotonic() + gemini.MIN_REQUEST_SEC >= run_budget.deadline:
            print("transcripts: time is up for this run")
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
        if mins > run_budget.minutes_left:
            print(f"the next video would exceed the {run_budget.minutes:g} min allowance")
            break
        available = [m for m in gemini.MODELS if m not in gemini._unavailable and not run_budget.model_spent(m)]
        if not available:
            print("every model's share for this run is used up")
            break
        v = data.get(a["id"]) or {}
        retell = bool(a.get("retell"))
        tried = set() if retell else set(v.get("vr", []))
        model_order = [m for m in available if m != RETELL_MODEL and m not in tried]
        if retell and (slot == "late" or not v.get("vt")) and RETELL_MODEL in available:
            model_order.insert(0, RETELL_MODEL)
        if not model_order:
            continue
        got, text, model = ask(a, api_key, mins, retell=retell, run_budget=run_budget, model_order=model_order)
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
            print(f"  + {a['artist_name']} - {a['album']} ({mins:.0f} min, {len(text)} characters, {model}"
                  + (", retold)" if retell else ")"))
        else:
            if retell:  # blocked: not asked again; else one more run
                v = {**v, "vt": FAIL_MAX if got == "blocked" else v.get("vt", 0) + 1}
            elif got == "refused":
                v = {**v, "vr": sorted(tried | {model}), "vf": FAIL_MAX}  # next: a retelling (RETELL)
            else:  # blocked: not asked again; bad: one more day
                v = {**v, "vf": FAIL_MAX if got == "blocked" else v.get("vf", 0) + 1}
            data[a["id"]] = v
            briefs.save(bpath, data)
            failed += 1
            print(f"  - {a['artist_name']} - {a['album']}: no usable {'retelling' if retell else 'transcript'} ({got}, {model})")
    used = run_budget.minutes - run_budget.minutes_left
    if slot:
        transcribe_quota.settle(quota_path, state, reservation, used, gemini.requests)
    print(f"transcripts: made {made}, unusable {failed}, "
          f"{used:.0f} min of video requested, HTTP requests by model: {gemini.requests}")


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


def cards(api_key, model, n=3):
    """The newest n new reviews' card texts written again by another model, the same way lmn/enrich.py writes them,
    next to what the card has now (owner, 2026-11-14: gemini-4-hydrogen against gemini-3.8-flash). Saves nothing."""
    from . import enrich
    gemini.MODELS[:] = [model]
    for r in sorted(_load("reviews.json", []), key=lambda r: r.get("published", ""))[-n:]:
        old = r.get("ai") or {}
        print(f"\n=== {r['title']} ({r.get('video_id')})")
        print(f"--- now ({old.get('m')}, {old.get('src')}, {old.get('sec')} s)")
        for k in ("brief", "about", "who", "moods"):
            print(f"{k}: {old.get(k)}")
        if old.get("src") == "text":
            text = tnd.fetch_texts([r["id"]]).get(r["id"]) or ""
            new = gemini.summarize(r["title"], text, api_key=api_key, tags=r.get("genres") or ())
        else:
            new = gemini.summarize(r["title"], video_id=r["video_id"], notes=enrich.video_notes(r), api_key=api_key,
                                   tags=r.get("genres") or ())
        new = new or {}
        print(f"--- {model} ({new.get('src')}, {new.get('sec')} s)")
        for k in ("brief", "about", "who", "moods"):
            print(f"{k}: {new.get(k)}")


PROBE_MAX = 3  # reviews a probe: each one is watched by every model, from the same daily share as new reviews


def probe(api_key, ids):
    """Why these reviews got no transcript: each one asked of every model in turn, with what each answered.
    Saves nothing, but spends the day's video share like a run: up to PROBE_MAX reviews and VIDEO_MINUTES minutes."""
    if len(ids) > PROBE_MAX:
        print(f"::warning::probe: {len(ids)} reviews, at most {PROBE_MAX} (each one is watched by every model)")
        return
    data = _load("briefs.json", {})
    items = [a for a in todo(_load("archive.json", []), {k: {**data.get(k, {}), "vf": 0} for k in ids}, set())
             if a["id"] in ids]
    if RETELL:
        print("probe: asking for a retelling, not a transcript")
    for k in set(ids) - {a["id"] for a in items}:
        print(f"{k}: not a review with only a retelling and a known video, skipped")
    lengths = minutes([a["video_id"] for a in items]) if items else {}
    left = VIDEO_MINUTES
    print(f"probe: up to {sum(lengths.values()) * len(gemini.MODELS):.0f} min of video")
    for a in items:
        mins = lengths.get(a["video_id"])
        print(f"{a['artist_name']} - {a['album']} ({a['video_id']}, {mins or 0:.0f} min)")
        if mins is None:
            print("  not on YouTube any more, skipped")
            continue
        for m in gemini.MODELS:
            if mins > left:
                print(f"  today's {VIDEO_MINUTES} min of video used up")
                return
            keep = set(gemini._unavailable)
            gemini._unavailable.update(x for x in gemini.MODELS if x != m)  # this model only
            try:
                got, text, model = ask(a, api_key, mins, retell=RETELL)
            finally:
                gemini._unavailable.clear()
                gemini._unavailable.update(keep)
            left -= mins
            print(f"  {m}: {got}" + (f", {len(text)} characters:" if text else ""))
            if text and RETELL:  # the whole retelling: a person reads it before RETELL is turned on for the daily run
                print(text)
            elif text:
                print(f"    {text[:200]!r}")

if __name__ == "__main__":
    if sys.argv[1:] == ["--claim-quota"]:
        claim_quota()
    else:
        run()
