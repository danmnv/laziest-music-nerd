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
        parts = [f"{e(p['album'])} — {label(p.get('score'), p.get('not_good'), p.get('classic'), unknown='?')}" for p in prev[:4]]
        text = "; ".join(parts)
        if len(prev) > 4:
            text += f" и ещё {len(prev) - 4}"
        if unsure:
            text += f" (ещё {unsure} — не уверен, тот ли артист)"
    a = r.get("artist") or {}
    begin = a.get("begin") if a.get("type") != "Person" else None  # for a person MusicBrainz 'begin' is the birth date
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


def plural_tracks(n):
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} трек"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} трека"
    return f"{n} треков"


def _norm(t):
    return "".join(ch for ch in (t or "").lower() if ch.isalnum())


def tracklist(r, limit=None):
    tracks = r.get("tracks") or []
    best = [_norm(b) for b in (r.get("ai") or {}).get("best_tracks", []) if _norm(b)]
    out = []
    for i, t in enumerate(tracks[:limit] if limit is not None else tracks, 1):
        n = _norm(t.get("title"))
        star = " ★" if n and any(b == n or (len(b) > 3 and b in n) for b in best) else ""
        dur = f" {t['sec'] // 60}:{t['sec'] % 60:02d}" if t.get("sec") else ""
        out.append(f"{i}. {e(t.get('title'))}{dur}{star}")
    if limit is not None and len(tracks) > limit:
        out.append(f"… ещё {len(tracks) - limit}")
    return out


def caption(r, _ai=None, _limit=None):
    ai = _ai if _ai is not None else (r.get("ai") or {})
    lines = [f"<b>{e(r['artist_name'])} — {e(r['album'])}</b>"]
    genres = ", ".join(r.get("genres", [])[:4])
    kind = TYPE_RU.get(r.get("type"))
    second = f"{EMOJI[color(r.get('score'), r.get('not_good'), r.get('classic'))]} {score_text(r)}"
    if kind:
        second += f" · {kind}"
    if genres:
        second += f" · {e(genres)}"
    size = [plural_tracks(len(r["tracks"])) if r.get("tracks") else None,
            f"{r['duration_min']} мин" if r.get("duration_min") else None]
    if any(size):
        second += " · " + ", ".join(x for x in size if x)
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
    if ai.get("brief"):
        lines.append(f"<b>Бриф:</b> {e(ai['brief'])}")
    if ai.get("moods"):
        lines.append(f"<b>Похоже на:</b> {e(' / '.join(ai['moods']))}?")
    tl = tracklist(r, _limit) if _limit != 0 else []
    if tl:
        legend = " (★ — выделил Фантано)" if any(x.endswith("★") for x in tl) else ""
        lines.append(f"<blockquote expandable><b>Треклист</b>{legend}\n" + "\n".join(tl) + "</blockquote>")
    text = "\n".join(lines)
    if len(text) <= CAPTION_LIMIT:
        return text
    # Too long for a photo caption: first shorten the tracklist, then the brief.
    n = len(r.get("tracks") or [])
    limit = n if _limit is None else _limit
    if limit > 0:
        return caption(r, ai, max(0, limit - 3) if limit > 3 else 0)
    if ai.get("brief"):
        cut = len(ai["brief"]) - (len(text) - CAPTION_LIMIT) - 1
        brief = ai["brief"][:cut].rstrip() + "…" if cut >= 40 else None
        return caption(r, {k: v for k, v in dict(ai, brief=brief).items() if v}, 0)
    return text[:CAPTION_LIMIT]


def buttons(r, with_callbacks=False):
    links = r.get("links") or {}
    row1 = [b for b in [
        {"text": "Bandcamp", "url": links["bandcamp"]} if links.get("bandcamp") else None,
        {"text": "YouTube Music", "url": links["ytmusic"]} if links.get("ytmusic") else None,
    ] if b]
    # The review itself is the YouTube video; the TND page (transcript) is linked from the site's release page.
    review = ({"text": "▶ Видеообзор", "url": f"https://youtu.be/{r['video_id']}"} if r.get("video_id")
              else {"text": "Обзор", "url": r["url"]})
    row2 = [b for b in [
        {"text": "Все платформы", "url": links["songlink"]} if links.get("songlink") else None,
        review,
    ] if b]
    rows = [row for row in (row1, row2) if row]
    if with_callbacks:
        sid = r["id"]
        rows.append([
            {"text": "• Отложить", "callback_data": f"m:{sid}:later"},
            {"text": "✓ Прослушано", "callback_data": f"m:{sid}:done"},
            {"text": "✗ Не понравилось", "callback_data": f"m:{sid}:nope"},
        ])
        moods = (r.get("ai") or {}).get("moods", [])
        for i, mood in enumerate(moods):
            rows.append([
                {"text": f"{mood}: да", "callback_data": f"v:{sid}:{i}:y"},
                {"text": "нет", "callback_data": f"v:{sid}:{i}:n"},
            ])
        if moods:
            rows.append([{"text": "Настроение: другое", "callback_data": f"v:{sid}:o"}])
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


LIST_HEAD = "<b>Свежие обзоры Фантано за 60 дней</b>\n\n"


def list_tail():
    return f'\n\n<a href="{SITE_URL}/">Полный список на сайте</a>' if SITE_LIVE else ""


def list_items(reviews, now=None):
    """Pre-rendered lines without statuses; the Worker appends each person's status itself."""
    return [{"id": r["id"], "line": list_line(r)} for r in recent(reviews, now=now)]


def render_list(items, statuses=None):
    statuses = statuses or {}
    lines = [i["line"] + STATUS.get(statuses.get(i["id"]), "") for i in items]
    tail = list_tail()
    while lines and len(LIST_HEAD + "\n".join(lines) + tail) > MESSAGE_LIMIT:
        lines.pop()
    return LIST_HEAD + ("\n".join(lines) if lines else "Пока пусто.") + tail


def pinned_text(reviews, statuses=None, now=None):
    return render_list(list_items(reviews, now=now), statuses)
