"""Gemini Flash: Russian brief, 'who is this', mood guesses. Returns None on any failure (empty field beats broken pipeline)."""
import json
import os
import time

from . import http

# gemini-2.5-flash is closed to new API keys (checked 2026-10-31: HTTP 404 "no longer available to new users").
MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash"
MOODS = ["для тренировки", "для настроения", "для работы за столом", "для тусовки"]

PROMPT = """Ты помогаешь вести русскоязычный Telegram-канал о музыкальных обзорах Anthony Fantano (The Needle Drop).
Ниже — расшифровка его видеообзора. Ответь строго JSON-объектом с полями:
- "brief": 1–2 предложения на русском, своими словами: что за релиз и что Фантано о нём думает. Не цитируй обзор, не переводи его дословно. До 220 символов.
- "who": 1 строка на русском о том, кто исполнитель (жанр/сцена, откуда, какой это по счёту релиз, если ясно из текста). Только факты из текста; если не ясно — пустая строка. До 140 символов.
- "moods": список из 1–2 вариантов ровно из этого набора: {moods}. Когда лучше всего слушать этот релиз.
- "best_tracks": до 3 названий треков, которые Фантано выделил как лучшие, точно как они написаны в тексте. Если не выделил — пустой список.
- "artist": имя исполнителя как в оригинале.
- "album": название релиза как в оригинале.
Названия альбомов, треков и жанров оставляй в оригинале.

Заголовок поста: {title}

Текст обзора:
{text}
"""


def summarize(title, text, api_key=None):
    api_key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key or not text:
        return None
    body = {
        "contents": [{"parts": [{"text": PROMPT.format(moods=json.dumps(MOODS, ensure_ascii=False), title=title, text=text[:30000])}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    for attempt in range(4):
        try:
            raw = http.get_json(url, json_body=body, method="POST", headers={"x-goog-api-key": api_key}, timeout=120, retries=0)
            out = json.loads(raw["candidates"][0]["content"]["parts"][0]["text"])
            out["moods"] = [m for m in out.get("moods", []) if m in MOODS][:2]
            return out
        except http.HttpError as e:
            print(f"gemini: HTTP {e.status} {_reason(e.body)}")
            if e.status not in (0, 429, 500, 503):  # timeout, overloaded or rate-limited: try again a bit later
                return None
            time.sleep(20 * (attempt + 1))
        except (KeyError, IndexError, ValueError) as e:
            print(f"gemini: bad response {e!r}")
            return None
    return None


def _reason(body):
    """Google's error message (says e.g. which quota ran out). Contains no key."""
    try:
        err = json.loads(body)["error"]
        quota = [v.get("quotaId") for d in err.get("details", []) for v in d.get("violations", []) if v.get("quotaId")]
        return (err.get("message") or "")[:200] + (f" quota={quota}" if quota else "")
    except Exception:
        return (body or "")[:200]
