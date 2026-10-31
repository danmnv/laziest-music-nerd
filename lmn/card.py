"""Channel card (photo caption + buttons) and the pinned 60-day list."""
import html
import os
from datetime import datetime, timedelta, timezone

from .colors import EMOJI, color, label

CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096
SITE_URL = os.environ.get("SITE_URL", "https://danmnv.github.io/laziest-music-nerd")
SITE_LIVE = os.environ.get("SITE_LIVE") == "1"  # until the site is up, list links go to the TND review
TYPE_RU = {"ep": "EP", "live": "live", "mixtape": "mixtape", "compilation": "сборник", "single": "сингл", "soundtrack": "саундтрек"}


def e(s):
    return html.escape(s or "", quote=False)


def score_text(r):
    if r.get("not_good"):
        return "NOT GOOD"
    if r.get("classic"):
        return "CLASSIC"
    if r.get("score") is None:
        return "без оценки"
    note = f" ({r['score_note']})" if r.get("score_note") else ""
    return f"{r['score']:g}/10{note}"


def fantano_before(r):
    prev = r.get("previous") or []
    unsure = r.get("previous_unsure") or 0
    if not prev and not unsure:
        text = "обозревает впервые"
    elif not prev:
        return f"не уверен: есть {unsure} обзор(а) артиста с таким же именем, но сверить по MusicBrainz не удалось"
    else:
        parts = [f"{e(p['album'])} — {label(p.get('score'), p.get('not_good'), p.get('classic'))}" for p in prev[:4]]
        text = "; ".join(parts)
        if len(prev) > 4:
            text += f" и ещё {len(prev) - 4}"
        if unsure:
            text += f" (ещё {unsure} — не уверен, тот ли артист)"
    begin = (r.get("artist") or {}).get("begin")
    if begin and begin[:4].isdigit() and int(begin[:4]) <= datetime.now().year - 10:
        text += f"; активны с {begin[:4]}"
    return text


def who_line(r):
    a = r.get("artist") or {}
    bits = []
    if r.get("ai", {}).get("who"):
        return e(r["ai"]["who"])
    if a.get("type"):
        bits.append({"Group": "группа", "Person": "сольный артист", "Orchestra": "оркестр", "Choir": "хор"}.get(a["type"], a["type"].lower()))
    if a.get("area"):
        bits.append(a["area"])
    return e(", ".join(bits)) or None


def caption(r):
    lines = [f"<b>{e(r['artist_name'])} — {e(r['album'])}</b>"]
    genres = ", ".join(r.get("genres", [])[:4])
    kind = TYPE_RU.get(r.get("type"))
    second = f"{EMOJI[color(r.get('score'), r.get('not_good'), r.get('classic'))]} {score_text(r)}"
    if kind:
        second += f" · {kind}"
    if genres:
        second += f" · {e(genres)}"
    if r.get("guest"):
        second += " · гостевой обзор"
    lines.append(second)
    lines.append("")
    who = who_line(r)
    if who:
        lines.append(f"<b>Кто:</b> {who}")
    before = fantano_before(r)
    if before:
        lines.append(f"<b>Фантано раньше:</b> {before}")
    ai = r.get("ai") or {}
    if ai.get("brief"):
        lines.append(f"<b>Бриф:</b> {e(ai['brief'])}")
    if ai.get("moods"):
        lines.append(f"<b>Похоже на:</b> {e(' / '.join(ai['moods']))}?")
    if r.get("video_id"):
        lines.append(f'\n<a href="https://youtu.be/{r["video_id"]}">Видеообзор на YouTube</a>')
    text = "\n".join(lines)
    while len(text) > CAPTION_LIMIT and ai.get("brief"):
        ai = dict(ai, brief=ai["brief"][: max(0, len(ai["brief"]) - (len(text) - CAPTION_LIMIT) - 1)] + "…")
        text = caption(dict(r, ai=ai))
    return text[:CAPTION_LIMIT]


def buttons(r, with_callbacks=False):
    links = r.get("links") or {}
    row1 = [b for b in [
        {"text": "Bandcamp", "url": links["bandcamp"]} if links.get("bandcamp") else None,
        {"text": "YouTube Music", "url": links["ytmusic"]} if links.get("ytmusic") else None,
    ] if b]
    row2 = [b for b in [
        {"text": "Все платформы", "url": links["songlink"]} if links.get("songlink") else None,
        {"text": "Обзор", "url": r["url"]},
    ] if b]
    rows = [row for row in (row1, row2) if row]
    if with_callbacks:
        sid = r["id"]
        rows.append([
            {"text": "• Отложить", "callback_data": f"m:{sid}:later"},
            {"text": "✓ Прослушано", "callback_data": f"m:{sid}:done"},
            {"text": "✗ Не понравилось", "callback_data": f"m:{sid}:nope"},
        ])
        for i, mood in enumerate((r.get("ai") or {}).get("moods", [])):
            rows.append([
                {"text": f"{mood}: да", "callback_data": f"v:{sid}:{i}:y"},
                {"text": "нет", "callback_data": f"v:{sid}:{i}:n"},
            ])
    return rows


def page_url(r):
    return f"{SITE_URL}/r/{r['id']}.html" if SITE_LIVE else r["url"]


STATUS = {"done": " ✓", "later": " •", "nope": " ✗"}


def list_line(r, status=None):
    parts = [f"{EMOJI[color(r.get('score'), r.get('not_good'), r.get('classic'))]} {label(r.get('score'), r.get('not_good'), r.get('classic'))}",
             f'<a href="{page_url(r)}">{e(r["artist_name"])} — {e(r["album"])}</a>']
    if r.get("genres"):
        parts.append(e(r["genres"][0]))
    if r.get("type") in TYPE_RU:
        parts.append(TYPE_RU[r["type"]])
    if r.get("duration_min"):
        parts.append(f"{r['duration_min']} мин")
    return " · ".join(parts) + STATUS.get(status, "")


def recent(reviews, days=60, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    rs = [r for r in reviews if datetime.fromisoformat(r["published"]) >= cutoff]
    return sorted(rs, key=lambda r: r["published"], reverse=True)


def pinned_text(reviews, statuses=None, now=None):
    statuses = statuses or {}
    rs = recent(reviews, now=now)
    head = "<b>Свежие обзоры Фантано за 60 дней</b>\n\n"
    tail = f'\n\n<a href="{SITE_URL}/">Полный список на сайте</a>' if SITE_LIVE else ""
    lines = [list_line(r, statuses.get(r["id"])) for r in rs]
    while lines and len(head + "\n".join(lines) + tail) > MESSAGE_LIMIT:
        lines.pop()
    if not lines:
        lines = ["Пока пусто."]
    return head + "\n".join(lines) + tail
