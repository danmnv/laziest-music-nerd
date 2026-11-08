"""Channel card (photo caption + buttons) and the channel's pinned list of the last 30 reviews."""
import html
import os
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

from . import gemini, tnd
from .colors import EMOJI, color, label

CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096
SITE_URL = os.environ.get("SITE_URL") or "https://laziest-music-nerd.pages.dev"  # an empty variable counts as unset
SITE_LIVE = os.environ.get("SITE_LIVE") == "1"  # until the site is up, list links go to the TND review
# With the Worker up, a title in the pinned list opens the album's card in the private chat with the bot
# (t.me/<bot>?start=a_<id>, worker/src/index.js openFromStart), not the site: a card can't go to the channel.
WORKER_LIVE = os.environ.get("WORKER_LIVE") == "1"
BOT_USERNAME = os.environ.get("BOT_USERNAME", "laziest_music_nerd_bot")
LIST_SIZE = 30
TYPE_RU = {"ep": "EP", "live": "live", "mixtape": "mixtape", "compilation": "сборник", "single": "сингл", "soundtrack": "саундтрек"}


def e(s):
    return html.escape(s or "", quote=False)


_TAG = re.compile(r"<[^>]+>")


def tg_len(s):
    """Length as Telegram counts it for the 1024/4096 limits: the visible text after HTML parsing (tags and link
    URLs don't count), in UTF-16 units (an emoji counts 2)."""
    return len(html.unescape(_TAG.sub("", s)).encode("utf-16-le")) // 2


def score_text(r):
    if r.get("not_good"):
        return "NOT GOOD"
    if r.get("classic"):
        return "CLASSIC"
    if r.get("not_bad"):
        return "NOT BAD"
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


def tracklist(r, limit=None, more_url=None):
    tracks = r.get("tracks") or []
    best = [_norm(b) for b in (r.get("ai") or {}).get("best_tracks", []) if _norm(b)]
    out = []
    for i, t in enumerate(tracks[:limit] if limit is not None else tracks, 1):
        n = _norm(t.get("title"))
        star = " ★" if n and any(b == n or (len(b) > 3 and b in n) for b in best) else ""
        dur = f" {t['sec'] // 60}:{t['sec'] % 60:02d}" if t.get("sec") else ""
        out.append(f"{i}. {e(t.get('title'))}{dur}{star}")
    if limit is not None and len(tracks) > limit:
        more = f"… ещё {len(tracks) - limit}"
        out.append(f'<a href="{html.escape(more_url)}">{more}</a>' if more_url else more)
    return out


CARD_V = 2  # the card's layout: 2 = the bot's and the channel's cards made the same (owner, 2026-11-08). A channel post
#            sent with an older layout is not edited any more (refresh): "уже опубликованные в канале не надо переписывать"


def nth_line(r):
    """«5-й из 5 обзоров артиста», as on the bot's card, instead of the old «Фантано раньше» line (owner, 2026-11-08:
    the channel has «💿 Альбомы артиста» for the rest). Nothing for an artist's first review."""
    n = len(r.get("previous") or [])
    return f"{n + 1}-й из {n + 1} обзоров артиста" if n else ""


def _caption(r, ai, limit, drop=()):
    name = f"{e(r['artist_name'])} — {e(r['album'])}"
    # plain text, not a link to the site: a link's text can't be copied in Telegram (owner, 2026-11-02); the year as
    # on the bot's card
    lines = [f"<b>{name}</b>" + (f" ({r['year']})" if r.get("year") else "")]
    genres = ", ".join(tnd.genres(r)[:4])
    kind = TYPE_RU.get(r.get("type"))
    second = f"{EMOJI[color(r.get('score'), r.get('not_good'), r.get('classic'))]} {score_text(r)}"
    if kind:
        second += f" · {kind}"
    if genres:
        second += f" · {e(genres)}"
    size = [plural_tracks(len(r["tracks"])) if r.get("tracks") else None,
            f"{r['duration_min']} мин" if r.get("duration_min") else None]
    if any(size):
        second += " · " + " · ".join(x for x in size if x)  # as on the bot's card
    if r.get("guest"):
        second += " · гостевой обзор"
    if nth_line(r):
        second += " · " + nth_line(r)
    lines.append(second)
    # paragraphs, the same as the bot's card (owner, 2026-11-08): title and score; who and the review's summary with no
    # blank line between them; critics; when to listen; the tracklist; the links and our site
    paras = ["\n".join(lines)]
    lines = []
    who = who_line(r) if "who" not in drop else None
    if who:
        lines.append(f"<b>Кто:</b> {who}")
    if ai.get("brief"):
        lines.append(f"<b>Обзор:</b> {e(ai['brief'])}")  # «Описание» renamed «Обзор» (owner, 2026-11-08)
    else:
        if r.get("blurb") and "blurb" not in drop:  # Fantano's own line under the video, in English as he wrote it
            lines.append(f"<b>Фантано под видео:</b> <i>{e(r['blurb'])}</i>")
        if r.get("brief_pending"):  # Gemini failed at posting time; refresh.py tries again and edits this post
            lines.append("<i>Обзор ещё пишется: допишется прямо в этот пост.</i>")
    paras.append("\n".join(lines))
    crit = critics_line(r) if "critics" not in drop else None
    if crit:
        paras.append(f"<b>Критики:</b> {crit}")
    moods = gemini.shown_moods(ai.get("moods"))[:2]  # the same list as the buttons (and the Worker's cardMoods)
    if moods and "moods" not in drop:
        paras.append(f"<b>Вайб для:</b> {e(' / '.join(gemini.vibe(m) for m in moods))} <i>(догадка ИИ, поправь кнопками)</i>")
    tl = tracklist(r, limit, more_url=tracks_url(r)) if limit != 0 else []
    if tl:
        legend = " (★ — выделил Фантано)" if any(x.endswith("★") for x in tl) else ""
        # the quote stands out by itself: no blank lines around it, the links right under it (owner, 2026-11-02)
        quote = f"<blockquote expandable><b>Треклист</b>{legend}\n" + "\n".join(tl) + "</blockquote>\n" + links_line(r)
        paras = [p for p in paras if p]
        paras[-1] += "\n" + quote
    else:
        paras.append(links_line(r))
    if SITE_LIVE:  # our site, worded so it can't be taken for the artist's or the album's (owner, 2026-11-02); right under
        # the links with no blank line, set apart by its own mark instead (owner, 2026-11-03)
        paras[-1] += f'\n{SITE_MARK} <a href="{page_url(r)}">{SITE_WORDS}</a>'
    return "\n\n".join(p for p in paras if p)


SITE_MARK = "🌐"  # the line with our site's page, on the channel's and the bot's cards
SITE_WORDS = "На нашем сайте"  # was «Этот альбом на нашем сайте» (owner, 2026-11-08: shorter)


def tracks_url(r):
    """The bot's link that sends the album's whole tracklist (title, score, genres, date, length and every track), for
    a card whose tracklist didn't fit (owner, 2026-11-08). None without the bot."""
    return f"https://t.me/{BOT_USERNAME}?start=t_{r['id']}" if WORKER_LIVE and r.get("id") else None


CARD_CRITICS = 3  # outlets on a card, in ratings.PRIORITY order (Pitchfork first), then Metacritic and AOTY; the same
#                  in the bot's card (lmn/site.py card_critics)


def critics_from(rt):
    """The few critic scores a card shows, from a data/ratings.json entry (with AOTY's merged in, aoty.merge):
    [{"o", "s", "u"}], or []."""
    if not rt or not (rt.get("wp") or rt.get("aoty") is not None or rt.get("critics")):
        return []
    out = [{"o": c["outlet"], "s": c["score"], "u": c.get("url")}
           for c in (rt.get("critics") or []) if c.get("outlet") and c.get("score")][:CARD_CRITICS]
    if rt.get("metacritic") is not None:
        out.append({"o": "Metacritic", "s": f"{rt['metacritic']}/100", "u": rt.get("mc_url")})
    if rt.get("aoty") is not None:  # an average like Metacritic's (owner, 2026-11-03)
        out.append({"o": "AOTY", "s": f"{rt['aoty']}/100"})
    return [{k: v for k, v in c.items() if v} for c in out]


def critics_line(r):
    """Plain text, no links: a card with a link on every outlet looks too busy (owner, 2026-11-02). The links are on
    the album's page on the site."""
    return " · ".join(f"{e(c['o'])} {e(c['s'])}" for c in r.get("critics") or [])


def caption(r):
    """Photo caption that always fits Telegram's 1024 limit. Never cuts through HTML: when the text is too long,
    whole parts go first (tracklist lines, then the brief's tail, then the less important lines)."""
    ai = r.get("ai") or {}
    n = len(r.get("tracks") or [])
    for limit in [*range(n, 0, -3), 0]:  # all tracks, then 3 fewer each time ("… ещё N"), then none
        text = _caption(r, ai, limit)
        if tg_len(text) <= CAPTION_LIMIT:
            return text
    brief = ai.get("brief") or ""
    if brief:
        keep = len(brief) - (tg_len(text) - CAPTION_LIMIT) - 1
        ai = dict(ai, brief=brief[:keep].rstrip() + "…" if keep >= 40 else None)
        text = _caption(r, ai, 0)
        if tg_len(text) > CAPTION_LIMIT:
            ai = dict(ai, brief=None)
    drop = []
    for part in (None, "moods", "blurb", "critics", "who"):
        if part:
            drop.append(part)
        text = _caption(r, ai, 0, drop)
        if tg_len(text) <= CAPTION_LIMIT:
            return text
    # Only an absurdly long artist/album name gets here: shorten the plain name, then escape it.
    short = dict(r, artist_name=(r["artist_name"] or "")[:200], album=(r["album"] or "")[:300])
    return _caption(short, {}, 0, drop)


SEARCH = "🔎 "  # a button that only searches, unlike one that opens the album itself


def bandcamp_label(url):
    """A Bandcamp button's label: a search is marked, the artist's own page (name.bandcamp.com) says so."""
    if "bandcamp.com/search" in url:
        return SEARCH + "Bandcamp"
    return "Bandcamp · артист" if re.match(r"https?://[a-z0-9-]+\.bandcamp\.com/?$", url, re.I) else "Bandcamp"


def link_rows(r):
    """The listening links as two rows of (label, url): what to hear it on, then all services. A link that only
    searches is marked with SEARCH; with no page of all services, Google is searched for the album."""
    links = r.get("links") or {}
    bc = links.get("bandcamp")
    row1 = [
        (bandcamp_label(bc), bc) if bc else None,
        ("YouTube (альбом)", links["youtube_album"]) if links.get("youtube_album") else
        (SEARCH + "YouTube Music", links["ytmusic"]) if links.get("ytmusic") else None,
    ]
    named = r.get("artist_name") and r.get("album")
    row2 = [
        ("Все платформы", links["songlink"]) if links.get("songlink") else
        (SEARCH + "Google", google_search(r["artist_name"], r["album"])) if named else None,
        # critics' and listeners' scores on Album of the Year: only a link to its search, nothing is fetched from it
        (SEARCH + "AOTY", aoty_search(r["artist_name"], r["album"])) if named else None,
    ]
    return [b for b in row1 if b], [b for b in row2 if b]


def aoty_search(artist, album):
    return "https://www.albumoftheyear.org/search/?" + urllib.parse.urlencode({"q": f"{artist} {album}"})


def google_search(artist, album):
    return "https://www.google.com/search?" + urllib.parse.urlencode({"q": f"{artist} {album}"})


def link_items(r):
    """The card's links as (label, url), in the order of the bot's cards (owner, 2026-11-02: buttons only for actions,
    links as text under the tracklist). A link that only searches says so ("искать …"); Apple Music only as the album
    itself (Music on a Mac drops a search link's query); no Bandcamp page known -> Google's search."""
    links = r.get("links") or {}
    named = r.get("artist_name") and r.get("album")
    q = urllib.parse.quote(f"{r.get('artist_name')} {r.get('album')}")
    bc = links.get("bandcamp")
    items = [
        ("Видеообзор", f"https://youtu.be/{r['video_id']}") if r.get("video_id") else ("Обзор", r.get("url")),
        ("YouTube Music", links["youtube_album"]) if links.get("youtube_album") else
        ("искать в YouTube Music", links.get("ytmusic") or f"https://music.youtube.com/search?q={q}") if named else None,
        ("Apple Music", links["apple"]) if links.get("apple") else None,
        ("искать в SoundCloud", f"https://soundcloud.com/search?q={q}") if named else None,
        # no «искать в Google» where no Bandcamp page is known (owner, 2026-11-08: no Google searches on cards)
        (bandcamp_label(bc).replace("Bandcamp · артист", "Bandcamp артиста"), bc) if bc and "bandcamp.com/search" not in bc else None,
        ("оценки на AOTY", aoty_search(r["artist_name"], r["album"])) if named else None,
    ]
    return [(t, u) for t, u in (x for x in items if x) if u]


def links_line(r):
    # no «Ссылки:» word (owner, 2026-11-08: their colour says they are links)
    return " · ".join(f'<a href="{html.escape(u)}">{e(t)}</a>' for t, u in link_items(r))


def buttons(r, with_callbacks=False):
    """Only actions (owner, 2026-11-02); the links are the caption's last line. Without the bot there are none."""
    rows = []
    if with_callbacks:
        sid = r["id"]
        # two a row, as the bot's card (worker MARK_ROWS); «♡ Понравилось» is its own mark (owner, 2026-11-02). A
        # channel post's buttons are the same for everyone, so the heart stays empty and the bot's answer says the state.
        rows.append([
            {"text": "✓ Слушал", "callback_data": f"m:{sid}:done"},
            {"text": "♡ Понравилось", "callback_data": f"lk:{sid}"},
        ])
        rows.append([
            {"text": "⏳ Послушать потом", "callback_data": f"m:{sid}:later"},
            {"text": "✗ Не моё", "callback_data": f"m:{sid}:nope"},
        ])
        # as the bot's card (worker artistButton): the artist's albums replace the old «Фантано раньше» line (owner, 2026-11-08)
        rows.append([{"text": "🔔 Следить", "callback_data": f"f:{sid}"},
                     {"text": "💿 Альбомы артиста", "callback_data": f"da:{sid}"}])
        # w:<id>:<index in MOODS>: MOODS only grows, so a button keeps meaning the same word (the Worker's handler)
        moods = gemini.shown_moods((r.get("ai") or {}).get("moods"))[:2]
        for mood in moods:
            i = gemini.MOODS.index(mood)
            rows.append([
                {"text": f"для {gemini.vibe(mood)}: да", "callback_data": f"w:{sid}:{i}:y"},
                {"text": "нет", "callback_data": f"w:{sid}:{i}:n"},
            ])
        if moods:
            rows.append([{"text": "Вайб: другое", "callback_data": f"v:{sid}:o"}])
    return rows


def page_url(r):
    return f"{SITE_URL}/r/{r['id']}.html" if SITE_LIVE else r["url"]


def list_url(r):
    return f"https://t.me/{BOT_USERNAME}?start=a_{r['id']}" if WORKER_LIVE else page_url(r)


STATUS = {"done": " ✓", "later": " ⏳", "nope": " ✗"}  # the same in worker STATUS_ICON


def list_line(r, status=None):
    parts = [f"{EMOJI[color(r.get('score'), r.get('not_good'), r.get('classic'))]} {label(r.get('score'), r.get('not_good'), r.get('classic'))}",
             f'<a href="{list_url(r)}">{e(r["artist_name"])} — {e(r["album"])}</a>']
    if tnd.genres(r):
        parts.append(e(tnd.genres(r)[0]))
    if r.get("type") in TYPE_RU:
        parts.append(TYPE_RU[r["type"]])
    if r.get("duration_min"):
        parts.append(f"{r['duration_min']} мин")
    return " · ".join(parts) + STATUS.get(status, "")


def recent(reviews, days=60, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    rs = [r for r in reviews if datetime.fromisoformat(r["published"]) >= cutoff]
    return sorted(rs, key=lambda r: datetime.fromisoformat(r["published"]), reverse=True)  # mixed "Z" and "-04:00" dates


LIST_HEAD = "<b>Последние 30 обзоров Фантано</b>\n\n"  # the same in worker/src/index.js
PIN_V = 4  # the pinned message's layout: check.py edits it once when this changes (2: the welcome, 3: likes and
#           «Послушать потом», 2026-11-02; 4: 👋 after «Привет!», 2026-11-05)


def pin_intro():
    """Above the channel's pinned list: a short welcome and how the channel and the bot work together, so a new
    subscriber isn't lost (owner, 2026-11-02). The same in worker/src/index.js pinIntro."""
    return ("<b>Привет!</b> 👋 Здесь мы знакомимся с новой музыкой, отталкиваясь от обзоров Anthony Fantano.\n\n"
            "<b>Канал:</b> карточка каждого нового обзора с оценкой, описанием, критиками, треклистом и ссылками, где послушать.\n"
            f'<b>Бот</b> <a href="https://t.me/{BOT_USERNAME}">@{BOT_USERNAME}</a>: поиск любого альбома из архива, '
            "«Наверстать» пропущенные обзоры, списки «Послушать потом» и «Понравившееся», сообщения о новых альбомах артистов, за которыми следишь.\n"
            "Кнопки под постами: «✓ Слушал»; «♡ Понравилось» — отдельный список, «Слушал» его не стирает; «⏳ Послушать потом» — эти альбомы идут первыми в «Наверстать»; «✗ Не моё». Кнопки видят все, а твои отметки только ты.\n"
            "Ниже 30 последних обзоров: нажми на альбом, и бот пришлёт его карточку.\n\n"
            "<i>Неофициальный проект, не связан с Anthony Fantano и The Needle Drop.</i>\n\n")


def list_tail():
    """Under the channel's pinned list: where the rest lives (the same in worker/src/index.js renderList)."""
    return (f'\n\n<a href="https://t.me/{BOT_USERNAME}">Бот</a>: поиск по архиву, «Наверстать», понравившееся'
            + (f' · <a href="{SITE_URL}/">сайт</a>' if SITE_LIVE else ""))


def latest(reviews, n=LIST_SIZE):
    return sorted(reviews, key=lambda r: datetime.fromisoformat(r["published"]), reverse=True)[:n]  # mixed "Z" and "-04:00"


def list_items(reviews, now=None):
    """The channel's pinned list: the last LIST_SIZE reviews, pre-rendered lines without statuses (the Worker appends
    the owner's when it edits the list after a mark)."""
    return [{"id": r["id"], "line": list_line(r)} for r in latest(reviews)]


def render_list(items, statuses=None):
    statuses = statuses or {}
    lines = [i["line"] + STATUS.get(statuses.get(i["id"]), "") for i in items]
    head, tail = pin_intro() + LIST_HEAD, list_tail()
    while lines and tg_len(head + "\n".join(lines) + tail) > MESSAGE_LIMIT:
        lines.pop()
    return head + ("\n".join(lines) if lines else "Пока пусто.") + tail


def pinned_text(reviews, statuses=None, now=None):
    return render_list(list_items(reviews, now=now), statuses)
