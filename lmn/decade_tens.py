"""Album cards from Fantano's five These Albums Are 10s episodes."""
import json
from pathlib import Path

from . import gemini
from .musicbrainz import norm

FILENAME = "decade-tens.json"
# The album lists are in the episode descriptions. The bot uses the same manifest.
_manifest = json.loads(Path(__file__).with_name("decade_tens_manifest.json").read_text(encoding="utf-8"))
EPISODES = {vid: (decade, date, tuple(map(tuple, items)))
            for vid, (decade, date, items) in _manifest["episodes"].items()}
ALIASES = {key: tuple(map(tuple, pairs)) for key, pairs in _manifest["aliases"].items()}
PREFIX = _manifest["prefix"]


# Original reviews linked by Fantano in the episode descriptions. These two archive posts lack a video ID.
ORIGINAL_VIDEOS = {
    "6684c32c49ea2a054e091111": "SqntE3jS43k",  # Marvin Gaye – What's Going On
    "6684c32c49ea2a054e091603": "u7JPMQkVuMo",  # Madvillain – Madvillainy
}


def video_url(vid, seconds=None):
    return f"https://youtu.be/{vid}" + (f"?t={seconds}" if seconds else "")


ALBUM_NAMES = {key: ((artist, title), *ALIASES.get(key, ()))
               for _, _, items in EPISODES.values() for key, artist, title, _ in items}


def album_keys(key, artist, title):
    return {(norm(a), norm(t)) for a, t in ((artist, title), *ALIASES.get(key, ()))}


EPISODE_ALBUM_KEYS = frozenset(
    pair
    for _, _, items in EPISODES.values()
    for key, artist, title, _ in items
    for pair in album_keys(key, artist, title)
)


def includes(review):
    return (norm(review.get("artist_name")), norm(review.get("album"))) in EPISODE_ALBUM_KEYS


def series_albums(archive):
    by_name = {}
    for a in sorted(archive, key=lambda a: a.get("published") or "", reverse=True):
        if not (a.get("guest") or a.get("dup_of") or a.get("track") or a.get("redo")):
            by_name.setdefault((norm(a.get("artist_name")), norm(a.get("album"))), a)
    for vid, (decade, date, items) in EPISODES.items():
        for key, artist, title, genre in items:
            matches = [by_name[k] for k in album_keys(key, artist, title) if k in by_name]
            existing = max(matches, key=lambda a: (not a["id"].startswith(PREFIX), a.get("published") or ""), default=None)
            yield vid, decade, key, existing or {
                "id": PREFIX + key, "artist_name": artist, "album": title, "genres": [genre],
                "published": date, "url": video_url(vid), "score": 10,
                "score_source": "decade-tens",
            }


def add_to_archive(archive):
    known = {a["id"] for a in archive}
    additions = [a for _, _, _, a in series_albums(archive) if a["id"] not in known]
    archive.extend(additions)
    return len(additions)


def card_sources(archive, cached):
    by_id = {}
    for vid, decade, key, a in series_albums(archive):
        segment = (cached.get("videos", {}).get(vid, {}).get("items") or {}).get(key) or {}
        by_id[a["id"]] = {
            # A dedicated review supplies its own text. Its episode segment is only a source link.
            **(segment if a["id"].startswith(PREFIX) else {}),
            "text": f"10/10 в выпуске про {decade}-е",
            "url": video_url(vid, segment.get("start_seconds")),
            "album": cached.get("albums", {}).get(key),
            "catalog_names": ALBUM_NAMES[key],
        }
    return by_id


PROMPT = """Посмотри и прослушай выпуск Anthony Fantano «These Albums Are 10s». Подготовь отдельный пересказ для каждого
альбома из списка ниже. Текст каждого пересказа должен опираться только на то, что Фантано действительно говорит в
сегменте об этом альбоме. Передай, как он описывает звучание и за что особенно ценит эту запись. Пиши естественным
русским языком, имена и названия оставляй в оригинале. Не цитируй Фантано, не повторяй оценку и название альбома
в пересказе. Не добавляй критику, контекст, факты или примеры, которых нет в сегменте. Пропусти спонсоров и отсылки
к другим альбомам. Если звук недоступен, верни пустой список. Если сегмент слишком короткий, пиши короче.

Верни JSON-объект с полем items (список объектов) и полями у каждого объекта:
- id: идентификатор из списка ниже, artist и album: соответствующие ему исполнитель и альбом из списка.
- start_seconds: целое число секунд, с которых начинается обсуждение именно этого альбома.
- brief: 1–3 предложения для Telegram, до 270 символов.
- about: более подробный пересказ для сайта, до 700 символов. Можно назвать треки, если он о них говорит.
- who: короткая справка об исполнителе, до 150 символов. Если в выпуске нет сведений, оставь поле пустым.
- moods: до двух вариантов из списка: {moods}. Оставь список пустым, если описание звучания недостаточно.

Альбомы:
{albums}
"""


def parse_answer(raw, albums, duration_seconds):
    """Require a usable, distinct segment for every album in the episode before saving."""
    expected = {key: album_keys(key, artist, title) for key, artist, title, _ in albums}
    cand = raw["candidates"][0]
    reason = cand.get("finishReason")
    if reason != "STOP":
        raise ValueError(f"generation ended with {reason!r}")
    parts = cand["content"]["parts"]
    answer = json.loads("".join(p.get("text", "") for p in parts if not p.get("thought")))["items"]
    if not isinstance(answer, list):
        raise ValueError("items must be a list")
    items, starts = {}, set()
    for row in answer:
        key, start = row["id"], row["start_seconds"]
        if key not in expected:
            raise ValueError("unexpected album ID")
        if key in items:
            raise ValueError(f"{key}: repeated album ID")
        if (norm(row["artist"]), norm(row["album"])) not in expected[key]:
            raise ValueError(f"{key}: artist or title does not match")
        if type(start) is not int or not 0 <= start < duration_seconds:
            raise ValueError(f"{key}: timestamp is not a whole number of seconds within the video")
        if start in starts:
            raise ValueError(f"{key}: same timestamp as another album")
        fields = {k: row[k].strip() for k in ("brief", "about") if isinstance(row.get(k), str)}
        if not fields.get("brief") or not fields.get("about"):
            raise ValueError(f"{key}: missing short or full description")
        who, moods = row.get("who"), row.get("moods")
        items[key] = {
            "start_seconds": start,
            "brief": gemini.trim_brief(gemini.drop_score(fields["brief"])),
            "about": gemini.trim_about(gemini.drop_score(fields["about"])),
            "who": gemini.tidy_who(who) if isinstance(who, str) else None,
            "moods": gemini.shown_moods(moods)[:2] if isinstance(moods, list) else [],
        }
        starts.add(start)
    if items.keys() != expected.keys():
        raise ValueError("missing albums: " + ", ".join(sorted(expected.keys() - items.keys())))
    return items


def request(vid, api_key, mins, **kwargs):
    albums = EPISODES[vid][2]
    prompt = PROMPT.format(moods=json.dumps(gemini.AI_MOODS, ensure_ascii=False),
                           albums="\n".join(f"{key}: {artist} — {title}" for key, artist, title, _ in albums))
    body = {"contents": [{"parts": [{"fileData": {"fileUri": f"https://www.youtube.com/watch?v={vid}"}}, {"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2,
                                 "mediaResolution": "MEDIA_RESOLUTION_LOW", "maxOutputTokens": 8192}}
    model, raw = gemini.generate(body, api_key, **kwargs)
    if raw is None:
        return None
    try:
        return {"model": model, "items": parse_answer(raw, albums, round(mins * 60))}
    except json.JSONDecodeError as e:
        detail = f"invalid JSON at line {e.lineno}, column {e.colno}"
    except ValueError as e:
        detail = str(e)
    except (AttributeError, KeyError, IndexError, TypeError) as e:
        detail = f"unexpected response structure ({type(e).__name__})"
    print(f"::warning::These Albums Are 10s {vid}: {model} response rejected: {detail}")
    return None


def save(path, cached):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cached, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)
