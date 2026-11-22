"""Album cards from Fantano's five These Albums Are 10s episodes."""
import json

from . import gemini
from .musicbrainz import norm

FILENAME = "decade-tens.json"
# The album lists are in the descriptions of the original uploads. Keep these IDs stable for saved marks.
EPISODES = {
    "erqGhrVB5Ao": (1960, "2022-12-06T23:32:50Z", (
        ("hot-rats", "Frank Zappa", "Hot Rats", "jazz rock"),
        ("highway-61", "Bob Dylan", "Highway 61 Revisited", "folk rock"),
        ("black-saint", "Charles Mingus", "The Black Saint and the Sinner Lady", "avant-garde jazz"),
        ("abbey-road", "The Beatles", "Abbey Road", "pop rock"),
        ("sings-the-blues", "Nina Simone", "Nina Simone Sings the Blues", "soul blues"),
    )),
    "csBo8Uj9kYY": (1970, "2022-10-07T02:04:51Z", (
        ("bitches-brew", "Miles Davis", "Bitches Brew", "jazz fusion"),
        ("london-calling", "The Clash", "London Calling", "punk rock"),
        ("whats-going-on", "Marvin Gaye", "What's Going On", "soul"),
        ("physical-graffiti", "Led Zeppelin", "Physical Graffiti", "hard rock"),
        ("marquee-moon", "Television", "Marquee Moon", "art rock"),
    )),
    "g4gMMIzwLO0": (1980, "2022-08-28T03:56:57Z", (
        ("master-of-puppets", "Metallica", "Master of Puppets", "thrash metal"),
        ("nation-of-millions", "Public Enemy", "It Takes a Nation of Millions to Hold Us Back", "hip hop"),
        ("hounds-of-love", "Kate Bush", "Hounds of Love", "art pop"),
        ("remain-in-light", "Talking Heads", "Remain in Light", "new wave"),
        ("purple-rain", "Prince and The Revolution", "Purple Rain", "pop rock"),
    )),
    "ab0XETmCUzM": (1990, "2022-08-03T05:35:14Z", (
        ("miseducation", "Lauryn Hill", "The Miseducation of Lauryn Hill", "neo-soul"),
        ("nevermind", "Nirvana", "Nevermind", "grunge"),
        ("aeroplane", "Neutral Milk Hotel", "In the Aeroplane Over the Sea", "indie folk"),
        ("36-chambers", "Wu-Tang Clan", "Enter the Wu-Tang (36 Chambers)", "hip hop"),
        ("violator", "Depeche Mode", "Violator", "synthpop"),
    )),
    "5rzBdM9CnRg": (2000, "2022-07-24T20:17:59Z", (
        ("discovery", "Daft Punk", "Discovery", "french house"),
        ("toxicity", "System of a Down", "Toxicity", "alternative metal"),
        ("vespertine", "Björk", "Vespertine", "art pop"),
        ("skinny-fists", "Godspeed You! Black Emperor", "Lift Yr. Skinny Fists Like Antennas to Heaven!", "post-rock"),
        ("madvillainy", "Madvillain", "Madvillainy", "hip hop"),
    )),
}

ALIASES = {
    "36-chambers": (("Wu-Tang Clan", "Enter the Wu-Tang: 36 Chambers"), ("Wu-Tang Clan", "36 Chambers")),
    "purple-rain": (("Prince", "Purple Rain"), ("Prince & The Revolution", "Purple Rain")),
    "skinny-fists": (("Godspeed You! Black Emperor", "Lift Your Skinny Fists Like Antennas to Heaven!"),),
    "madvillainy": (("Madvillainy", "Madvillain"),),
}
PREFIX = "ten-"


def video_url(vid, seconds=None):
    return f"https://youtu.be/{vid}" + (f"?t={seconds}" if seconds else "")


def album_keys(key, artist, title):
    return {(norm(a), norm(t)) for a, t in ((artist, title), *ALIASES.get(key, ()))}


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
        about = (cached.get("videos", {}).get(vid, {}).get("items") or {}).get(key) or {}
        by_id[a["id"]] = {
            **about, "text": f"10/10 в выпуске про {decade}-е",
            "url": video_url(vid, about.get("start_seconds")),
            "album": cached.get("albums", {}).get(key),
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
    if cand.get("finishReason") != "STOP":
        raise ValueError("incomplete response")
    parts = cand["content"]["parts"]
    answer = json.loads("".join(p.get("text", "") for p in parts if not p.get("thought")))["items"]
    items, starts = {}, set()
    for row in answer:
        key, start = row["id"], row["start_seconds"]
        if (key in items or (norm(row["artist"]), norm(row["album"])) not in expected[key]
                or type(start) is not int or not 0 <= start < duration_seconds or start in starts):
            raise ValueError("wrong album or invalid timestamp")
        fields = {k: row[k].strip() for k in ("brief", "about") if isinstance(row.get(k), str)}
        if not fields.get("brief") or not fields.get("about"):
            raise ValueError("missing description")
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
        raise ValueError("incomplete album list")
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
    except (AttributeError, KeyError, IndexError, TypeError, ValueError) as e:
        print(f"::warning::These Albums Are 10s {vid}: rejected Gemini response ({type(e).__name__})")
        return None


def save(path, cached):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cached, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)
