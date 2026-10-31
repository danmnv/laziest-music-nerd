"""Gemini Flash: Russian brief, 'who is this', mood guesses. Returns None on any failure (empty field beats broken pipeline)."""
import json
import os
import re
import time

from . import http

# The free tier has a daily request limit per model ("GenerateRequestsPerDayPerProjectPerModel-FreeTier", seen
# 2026-10-31), so when one model's day is used up the next one in this list is tried. Any of them writes the brief well.
# gemini-2.5-flash is not here: it is closed to new API keys (HTTP 404 "no longer available to new users").
MODELS = [m.strip() for m in (os.environ.get("GEMINI_MODEL") or
                              "gemini-3.8-flash,gemini-3.7-flash,gemini-3.5-flash,gemini-3.5-flash-lite").split(",") if m.strip()]
MODEL = MODELS[0]
BUDGET_SEC = 240      # per review, all models and retries together, so a slow day can't eat the hourly run
CALL_TIMEOUT = 90
MOODS = ["для тренировки", "для настроения", "для работы за столом", "для тусовки"]
_unavailable = set()  # models found used up for today (or closed) during this run: skipped for the next reviews

PROMPT = """Ты помогаешь вести русскоязычный Telegram-канал о музыкальных обзорах Anthony Fantano (The Needle Drop).
{source} Ответь строго JSON-объектом с полями:
- "brief": 1–2 предложения на русском, своими словами: что за релиз и что Фантано о нём думает. Не цитируй обзор, не переводи его дословно. До 220 символов.
- "who": 1 строка на русском о том, кто исполнитель (жанр/сцена, откуда, какой это по счёту релиз, если ясно из текста). Только факты из текста; если не ясно — пустая строка. До 140 символов.
- "moods": список из 1–2 вариантов ровно из этого набора: {moods}. Когда лучше всего слушать этот релиз.
- "best_tracks": до 3 названий треков, которые Фантано выделил как лучшие, точно как они написаны в тексте. Если не выделил — пустой список.
- "artist": имя исполнителя как в оригинале.
- "album": название релиза как в оригинале.
- "score_note": если Фантано назвал оценку вместе со словом light, decent или strong (например «a strong 7» или «light to decent 6»), это слово или пара слов по-английски строчными буквами; иначе пустая строка.
Названия альбомов, треков и жанров оставляй в оригинале.

Заголовок: {title}
{text}"""
SOURCE_TEXT = "Ниже — расшифровка его видеообзора."
SOURCE_VIDEO = "Выше — сам его видеообзор на YouTube; ниже — описание видео."
NOTE = re.compile(r"^(?:light|decent|strong)(?: to (?:light|decent|strong))?$")


def generate(body, api_key, budget=BUDGET_SEC, sleep=time.sleep, clock=time.monotonic):
    """POST generateContent, walking down MODELS. Returns (model, response) or (None, None)."""
    deadline = clock() + budget
    for model in MODELS:
        if model in _unavailable:
            continue
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            left = deadline - clock()
            if left < 15:
                print("gemini: time budget for this review used up")
                return None, None
            try:
                return model, http.get_json(url, json_body=body, method="POST", headers={"x-goog-api-key": api_key},
                                            timeout=min(CALL_TIMEOUT, left), retries=0)
            except http.HttpError as e:
                print(f"gemini {model}: HTTP {e.status} {_reason(e.body)}")
                if e.status == 404 or (e.status == 429 and "PerDay" in e.body):
                    _unavailable.add(model)  # closed to this key, or today's limit is gone: next model right away
                    break
                if e.status not in (0, 429, 500, 503):  # a bad key or request: no other model will do better
                    return None, None
                wait = 30 if "PerMinute" in e.body else 10
                if attempt == 0 and deadline - clock() > wait + 15:  # timeout, overload or per-minute limit:
                    sleep(wait)                                       # one more try a bit later, then the next model
    print("gemini: no model answered")
    return None, None


def summarize(title, text=None, api_key=None, video_id=None, notes=""):
    """From the transcript (text) or, when there is none yet, from the video itself (video_id; notes = its description)."""
    api_key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key or not (text or video_id):
        return None
    moods = json.dumps(MOODS, ensure_ascii=False)
    if text:
        parts = [{"text": PROMPT.format(source=SOURCE_TEXT, moods=moods, title=title, text="\nТекст обзора:\n" + text[:30000])}]
        config = {}
    else:
        parts = [{"fileData": {"fileUri": f"https://www.youtube.com/watch?v={video_id}"}},
                 {"text": PROMPT.format(source=SOURCE_VIDEO, moods=moods, title=title, text="\nОписание видео:\n" + (notes or "")[:3000])}]
        config = {"mediaResolution": "MEDIA_RESOLUTION_LOW"}  # ~45k tokens for a 8-minute review instead of ~130k
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4, **config}}
    model, raw = generate(body, api_key)
    if raw is None:
        return None
    try:
        out = json.loads(raw["candidates"][0]["content"]["parts"][0]["text"])
        if isinstance(out, list):  # gemini-3.5-flash sometimes wraps the object in a list (seen 2026-10-31 on HMLTD)
            out = next((x for x in out if isinstance(x, dict)), None)
        if not isinstance(out, dict):
            raise ValueError(f"expected a JSON object, got {type(out).__name__}")
        out["moods"] = [m for m in out.get("moods", []) if m in MOODS][:2]
        note = str(out.get("score_note") or "").strip().lower()
        out["score_note"] = note if NOTE.match(note) else None
        return out
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
        print(f"gemini {model}: bad response {e!r}")
        return None


def _reason(body):
    """Google's error message (says e.g. which quota ran out and its size). Contains no key."""
    try:
        err = json.loads(body)["error"]
        quota = [f"{v['quotaId']}={v.get('quotaValue', '?')}" for d in err.get("details", [])
                 for v in d.get("violations", []) if v.get("quotaId")]
        return (err.get("message") or "")[:200] + (f" quota={quota}" if quota else "")
    except Exception:
        return (body or "")[:200]
