"""Build the static site (GitHub Pages) from data/*.json into _site/."""
import hashlib
import html
import json
import os
import shutil
import unicodedata
import urllib.parse
from pathlib import Path

from . import card, specials, tnd
from .colors import color, label
from .musicbrainz import norm

DATA = Path(os.environ.get("DATA_DIR", "data"))
SRC = Path("site_src")
OUT = Path(os.environ.get("SITE_OUT", "_site"))
DISCLAIMER = "Неофициальный фан-проект. Не связан с Anthony Fantano и The Needle Drop. Оценки и обзоры — их; ссылки ведут на оригиналы."


def e(s):
    return html.escape(str(s or ""))


def load(name, default):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else default


FONTS = "https://fonts.googleapis.com/css2?family=Onest:wght@400;500;700&family=Unbounded:wght@600;800&display=swap"
CHANNEL = "laziestmusicnerd"
BOT = "laziest_music_nerd_bot"


def page(title, body, depth=0):
    up = "../" * depth
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{e(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}"><link rel="stylesheet" href="{up}style.css"><link rel="manifest" href="{up}manifest.json">
<meta name="theme-color" content="#f4f1ea" media="(prefers-color-scheme: light)"><meta name="theme-color" content="#121116" media="(prefers-color-scheme: dark)">
<link rel="icon" href="{up}icon.svg"><link rel="apple-touch-icon" href="{up}apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="LMN"></head>
<body><header class="top"><div class="bar">
<a class="logo" href="{up}index.html"><img src="{up}icon.svg" alt="" width="28" height="28"><span class="full">Laziest<b> Music Nerd</b></span><span class="short">LMN</span></a>
<nav><a class="fresh" href="{up}index.html#fresh">Свежее</a><a href="{up}index.html#catalog-h">Каталог</a><a class="find" href="{up}index.html#search" aria-label="Поиск"><svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><circle cx="7.5" cy="7.5" r="5.5"/><path d="m12 12 4.5 4.5"/></svg></a></nav>
<span id="login"></span></div></header>
<main>{body}</main>
<footer><p class="links"><a href="https://t.me/{CHANNEL}">Канал в Telegram</a><a href="https://t.me/{BOT}">Бот</a><a href="https://www.youtube.com/@theneedledrop">The Needle Drop</a></p>
<p>{e(DISCLAIMER)}</p></footer>
<script>window.LMN={{root:"{up}",worker:{json.dumps(worker_url())},bot:"{BOT}"}}</script>
<script src="{up}app.js"></script></body></html>"""


def worker_url():
    f = DATA / "worker_url.txt"
    return f.read_text().strip() if f.exists() else ""


# Latin letters that NFKD doesn't split into a base letter + mark (so they'd be lost on the way to ASCII)
TRANSLIT = str.maketrans({"ø": "o", "Ø": "O", "ı": "i", "æ": "ae", "Æ": "AE", "ß": "ss", "ł": "l", "Ł": "L", "đ": "d", "Đ": "D",
                          "œ": "oe", "Œ": "OE", "þ": "th", "Þ": "TH", "ð": "d", "Ð": "D"})


def slug(name):
    """The artist page's file name: the plain-Latin name (Björk -> bjork), or a hash when letters would be lost on
    the way to Latin (Кино, 坂本龍一 & X), so two such artists never share a page. Names that normalise alike
    ("Low", "LOW") share one, as in the bot's search."""
    name = (name or "").translate(TRANSLIT)
    lost = any(ch.isalpha() and not unicodedata.normalize("NFKD", ch).encode("ascii", "ignore") for ch in name)
    k = norm(name)
    return k[:60] if k and not lost else "x" + hashlib.sha1(name.encode()).hexdigest()[:10]


def score_badge(a):
    if a.get("track"):
        return '<span class="score none">трек</span>'
    c = color(a.get("score"), a.get("not_good"), a.get("classic")) or "none"
    return f'<span class="score {c}">{e(card.score_text(a))}</span>'


def history_list(items, current_id, depth):
    """An artist's reviews, newest first, the current one unlinked."""
    up = "../" * depth
    li = []
    for x in items:
        name = e(x["album"]) if x["id"] == current_id else f'<a href="{up}r/{e(x["id"])}.html">{e(x["album"])}</a>'
        li.append(f'<li data-id="{e(x["id"])}">{score_badge(x)} {name}'
                  f'<span class="muted"> · обзор {e(x["published"][:4])}{" · гостевой" if x.get("guest") else ""}</span><span class="st"></span></li>')
    return f'<ul class="list">{"".join(li)}</ul>'


def search_buttons(artist, album):
    q = urllib.parse.quote_plus(f"{artist} {album}")
    return [("🔎 YouTube Music", f"https://music.youtube.com/search?q={q}"), ("🔎 Google", f"https://www.google.com/search?q={q}"),
            ("🔎 Оценки на AOTY", card.aoty_search(artist, album))]


def critics_parts(rt):
    """Critic scores and chart/sales facts from data/ratings.json (the ratings workflow; source: the album's
    Wikipedia article). Two lists of short strings; both empty when there's no article."""
    if not rt or not rt.get("wp"):
        return [], []
    crit = []
    if rt.get("metacritic") is not None:
        crit.append(f"Metacritic {rt['metacritic']}")
    if rt.get("adm") is not None:
        crit.append(f"AnyDecentMusic {rt['adm']:g}")
    crit += [f"{c['outlet']} {c['score']}" for c in (rt.get("critics") or [])[:5] if c.get("outlet") and c.get("score")]
    sales = [f"{k} #{v}" for k, v in (rt.get("charts") or {}).items() if v]
    sales += [f"{c['region']} {c['award']}" for c in rt.get("certs") or [] if c.get("region") and c.get("award")]
    return crit, sales


def contested(a, rt):
    """'Спорно' (spec, v2): Fantano's score and the critics' average are 4+ points apart on a 10-point scale.
    The average is Metacritic/10, else the mean of 3+ numeric scores (data/ratings.json critic_avg10); text or None."""
    if not rt or not rt.get("wp") or a.get("guest") or a.get("score") is None or rt.get("critic_avg10") is None:
        return None
    avg = rt["critic_avg10"]
    if abs(a["score"] - avg) < 4:
        return None
    src = "Metacritic" if not rt.get("critic_avg_n") else f"среднее по {rt['critic_avg_n']} изданиям"
    return f"Фантано {a['score']}/10, критики {avg:g}/10 ({src})"


def notes_rows(n, rid=None):
    """Fantano's own line from the video description (his favourite tracks are fav_section, below the buttons)."""
    if not n or not n.get("blurb"):
        return []
    return [("Фантано в описании ролика", f'<q lang="en">{e(n["blurb"])}</q>')]


def fav_section(n):
    """Fantano's favourite tracks under the page's main part, each opening an official player on a tap: Deezer's
    widget, or Apple Music's embed for a track Deezer doesn't have (both play 30-second previews; embedding them is
    what they are offered for, unlike handing out the audio). Closed, a player isn't loaded (checked in Chromium 153)."""
    fav = (n or {}).get("fav") or []
    if not fav:
        return ""
    items = []
    for f in fav:
        if f.get("dz"):  # the attributes of Deezer's own embed code
            who, attrs = "Deezer", (f'src="https://widget.deezer.com/widget/auto/track/{int(f["dz"])}" height="152" '
                                    'allow="encrypted-media; clipboard-write"')
        elif f.get("am"):  # the attributes of Apple's own embed code
            who, attrs = "Apple Music", (f'src="https://embed.music.apple.com/{e(f["am"])}" height="175" '
                                         'allow="autoplay *; encrypted-media *; fullscreen *; clipboard-write" '
                                         'sandbox="allow-forms allow-popups allow-same-origin allow-scripts '
                                         'allow-storage-access-by-user-activation allow-top-navigation-by-user-activation"')
        else:
            items.append(f'<li><span class="trk">{e(f["t"])}</span></li>')
            continue
        items.append(f'<li><details><summary><span class="trk">{e(f["t"])}</span> <span class="muted">▶ {who}</span></summary>'
                     f'<iframe class="dz" title="{who}: {e(f["t"])}" loading="lazy" {attrs} width="100%" frameborder="0"></iframe></details></li>')
    return f'<section class="favs"><h2 id="fav">Любимые треки Фантано</h2><ul>{"".join(items)}</ul></section>'


def lists_rows(badges):
    """Fantano's lists and rankings the album is in (lmn/specials.py), each linking to its video."""
    if not badges:
        return []
    return [("У Фантано в списках", "<br>".join(f'🏆 <a href="{e(b["url"])}">{e(b["text"])}</a>' for b in badges))]


def critics_rows(rt, a=None):
    rows = []
    sp = contested(a or {}, rt)
    if sp:
        rows.append(("Спорно", f'<span class="contested">⚡ {e(sp)}</span>'))
    crit, sales = critics_parts(rt)
    src = f' <a class="muted" href="{e(rt["wp_url"])}">по данным Википедии</a>' if (crit or sales) and rt.get("wp_url") else ""
    if crit:
        rows.append(("Критики", e(" · ".join(crit)) + src))
    if sales:
        rows.append(("Чарты и продажи", e(" · ".join(sales)) + src))
    return rows


def archive_page(a, artist_reviews, rt=None, lists=None, note=None, brief=None, album=None):
    """A release page for a review the bot never posted a card for: what the archive knows, the artist's other
    reviews, and the reader's marks."""
    review = f"https://youtu.be/{a['video_id']}" if a.get("video_id") else a["url"]
    btns = [("▶ Видеообзор" if a.get("video_id") else "Обзор", review)]
    if a.get("video_id") and "theneedledrop.com" in a["url"]:
        btns.append(("Текст обзора на TND", a["url"]))
    # what the bot's card shows for this album, from Deezer (data/albums.json, lmn/notes.py)
    album = album or {}
    if album.get("dz"):
        btns.append(("Все платформы", f"https://album.link/https://www.deezer.com/album/{int(album['dz'])}"))
    btns += search_buttons(a["artist_name"], a["album"])
    year = album.get("y") if (album.get("y") or "9999") <= a["published"][:4] else None  # Deezer may only have a later reissue
    by_date = sorted(artist_reviews, key=lambda x: x["published"])
    nth = next((i for i, x in enumerate(by_date, 1) if x["id"] == a["id"]), 0)
    meta = " · ".join(x for x in [", ".join((a.get("genres") or [])[:5]),
                                    card.plural_tracks(len(album["t"])) if album.get("t") else None,
                                    f"{album['min']} мин" if album.get("min") else None,
                                    "обзор " + a["published"][:10], "гостевой обзор" if a.get("guest") else None,
                                    f"{nth}-й из {len(by_date)} обзоров артиста" if nth and len(by_date) > 1 else None] if x)
    others = [x for x in artist_reviews if x["id"] != a["id"]]
    hist = (f'<h2>Фантано об этом артисте</h2>{history_list(artist_reviews, a["id"], 1)}' if others else "")
    brief = brief or {}
    rows = [(k, e(v)) for k, v in (("Кто", brief.get("who")), ("Бриф", brief.get("about") or brief.get("brief"))) if v]
    # Fantano's line only where there's no brief (as on bot-card pages)
    rows += notes_rows({**(note or {}), "blurb": None if brief.get("brief") else (note or {}).get("blurb")} if note else None, a["id"])
    if album.get("t"):  # Fantano's favourites marked with ★, as on bot-card pages
        fav = {"tracks": [{"title": t, "sec": sec} for t, sec in album["t"]], "ai": {"best_tracks": [f["t"] for f in (note or {}).get("fav") or []]}}
        rows.append(("Треклист", "<ol>" + "".join(f"<li>{line.split('. ', 1)[1]}</li>" for line in card.tracklist(fav)) + "</ol>"
                     + ('<span class="muted">★ — любимые у Фантано</span>' if fav["ai"]["best_tracks"] else "")))
    rows += lists_rows(lists) + critics_rows(rt, a)
    # the mood row stays hidden until app.js fills it from visitors' votes (/api/public)
    dl = (f"<dl>{''.join(f'<dt>{k}</dt><dd>{v}</dd>' for k, v in rows)}"
          '<dt class="moods-h" hidden>Когда слушать</dt><dd class="moods" hidden></dd></dl>')
    body = f"""<article class="release" data-id="{e(a['id'])}">
{f'<img class="cover" src="{e(album["cv"])}" alt="">' if album.get("cv") else ''}
<h1><a href="../a/{slug(a['artist_name'])}.html">{e(a['artist_name'])}</a> — {e(a['album'])}{f' <span class="muted">({e(year)})</span>' if year else ''}</h1>
<p>{score_badge(a)} <span class="muted">{e(meta)}</span></p>
{dl}
<p class="btns">{''.join(f'<a class="btn" href="{e(u)}">{e(n)}</a>' for n, u in btns)}</p>
<div class="mine" hidden></div>
<p class="avg muted"></p>
{fav_section(note)}
{hist}
</article>"""
    return page(f"{a['artist_name']} — {a['album']}", body, depth=1)


def reviews_word(n):
    return f"{n} " + ("обзор" if n % 10 == 1 and n % 100 != 11 else "обзора" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "обзоров")


def artist_page(name, items):
    body = f"""<h1>{e(name)}</h1>
<p class="muted">{reviews_word(len(items))} Фантано</p>
{history_list(items, None, 1)}"""
    return page(name, body, depth=1)


def dossier_rows(d):
    """Rows from data/artists.json (lmn/dossier.py): the Wikipedia paragraph and the band's members."""
    if not d or not d.get("title"):
        return []
    rows = []
    src = f' <a class="muted" href="{e(d["url"])}">Википедия</a>'
    if d.get("extract"):
        rows.append(("Об артисте", f'<span class="dossier">{e(d["extract"])}</span>{src}'))
    if d.get("members"):
        rows.append(("Состав", f'<span class="dossier">{e(", ".join(d["members"]))}</span>'))
    if d.get("past_members"):
        rows.append(("Бывшие участники", f'<span class="dossier">{e(", ".join(d["past_members"]))}</span>'))
    return rows


def release_page(r, rt=None, wiki=None, lists=None, note=None, brief=None):
    c = color(r.get("score"), r.get("not_good"), r.get("classic"))
    a = r.get("artist") or {}
    ai = r.get("ai") or {}
    if brief and brief.get("brief") and not ai.get("brief"):  # the card went out without one (seeded, or Gemini was out of quota): the archive's
        ai = {**ai, "brief": brief.get("brief"), "about": brief.get("about"), "who": ai.get("who") or brief.get("who"), "moods": ai.get("moods") or brief.get("moods")}
    rows = []
    if ai.get("who"):
        rows.append(("Кто", e(ai["who"])))
    before = card.fantano_before(r)
    if before:
        rows.append(("Фантано раньше", before))
    if ai.get("brief"):  # the site has room for the longer one; the card in Telegram keeps the short one
        rows.append(("Бриф", e(ai.get("about") or ai["brief"])))
    if ai.get("moods"):
        rows.append(("Когда слушать", '<span class="moods">' + e(" / ".join(ai["moods"])) + ' <span class="muted">(догадка ИИ)</span></span>'))
    dossier = []
    if a.get("type"):
        dossier.append({"Group": "группа", "Person": "сольный артист"}.get(a["type"], a["type"]))
    if a.get("area"):
        dossier.append(a["area"])
    if a.get("begin"):
        dossier.append(("родился " if a.get("type") == "Person" else "с ") + a["begin"][:4])
    if a.get("aliases"):
        dossier.append("также: " + ", ".join(a["aliases"]))
    if dossier:
        rows.append(("Досье", e(" · ".join(dossier))))
    rows += dossier_rows(wiki)
    if r.get("tracks"):
        rows.append(("Треклист", "<ol>" + "".join(f"<li>{line.split('. ', 1)[1]}</li>" for line in card.tracklist(r)) + "</ol>"
                     + ('<span class="muted">★ — выделил Фантано</span>' if (r.get("ai") or {}).get("best_tracks") else "")))
    # Fantano's line only where there's no brief; the favourites' players below the buttons (fav_section)
    rows += notes_rows({"blurb": None if ai.get("brief") else (note or {}).get("blurb")}, r["id"])
    rows += lists_rows(lists)
    rows += critics_rows(rt, r)
    if r.get("previous"):
        hist = "".join(f'<li><a href="{e(p["url"])}">{e(p["album"])}</a> — {label(p.get("score"), p.get("not_good"), p.get("classic"), "?")} <span class="muted">{e(p["published"][:4])}</span></li>' for p in r["previous"])
        rows.append(("История оценок", f"<ul>{hist}</ul>"))
    top, alls = card.link_rows(r)
    btns = "".join(f'<a class="btn" href="{e(u)}">{e(n)}</a>' for n, u in top + alls + [
        ("Текст обзора на TND", r.get("tnd_url") or (r["url"] if "theneedledrop.com" in r["url"] else None)),
        ("Видео", f"https://youtu.be/{r['video_id']}" if r.get("video_id") else None)] if u)
    meta = " · ".join(x for x in [", ".join(r.get("genres", [])[:5]), card.TYPE_RU.get(r.get("type")),
                                    f"{r['duration_min']} мин" if r.get("duration_min") else None, r["published"][:10],
                                    "гостевой обзор" if r.get("guest") else None] if x)
    cover = (r.get("covers") or [None])[0]
    body = f"""<article class="release" data-id="{e(r['id'])}">
{f'<img class="cover" src="{e(cover)}" alt="">' if cover else ''}
<h1><a href="../a/{slug(r['artist_name'])}.html">{e(r['artist_name'])}</a> — {e(r['album'])}</h1>
<p><span class="score {c or 'none'}">{card.score_text(r)}</span> <span class="muted">{e(meta)}</span></p>
<dl>{''.join(f'<dt>{k}</dt><dd>{v}</dd>' for k, v in rows)}</dl>
<p class="btns">{btns}</p>
<div class="mine" hidden></div>
<p class="avg muted"></p>
{fav_section(note)}
</article>"""
    return page(f"{r['artist_name']} — {r['album']}", body, depth=1)


def catalog_entry(a):
    return {"i": a["id"], "a": a.get("artist_name") or "", "t": a.get("album") or "", "s": a.get("score"),
            "ng": 1 if a.get("not_good") else 0, "cl": 1 if a.get("classic") else 0, "d": a["published"][:10],
            "g": (a.get("genres") or [])[:4], "k": slug(a.get("artist_name")), "gu": 1 if a.get("guest") else 0,
            **({"tr": 1} if a.get("track") else {})}


def recent_item(r):
    c = color(r.get("score"), r.get("not_good"), r.get("classic")) or "none"
    extra = [(r.get("genres") or [None])[0], card.TYPE_RU.get(r.get("type")),
             f"{r['duration_min']} мин" if r.get("duration_min") else None]
    return (f'<li data-id="{e(r["id"])}"><span class="score {c}">{label(r.get("score"), r.get("not_good"), r.get("classic"))}</span> '
            f'<a href="r/{e(r["id"])}.html">{e(r["artist_name"])} — {e(r["album"])}</a>'
            f'<span class="muted"> {e(" · ".join(x for x in extra if x))}</span><span class="st"></span></li>')


def build():
    reviews = load("reviews.json", [])
    archive = [tnd.tidy_entry(a) for a in load("archive.json", [])]
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(SRC, OUT)
    (OUT / "r").mkdir(exist_ok=True)
    (OUT / "a").mkdir(exist_ok=True)
    by_id = {a["id"]: a for a in archive if a.get("artist_name") and a.get("album")}
    for r in reviews:
        by_id[r["id"]] = r
    by_artist = {}
    for a in by_id.values():
        by_artist.setdefault(slug(a["artist_name"]), []).append(a)
    for items in by_artist.values():
        items.sort(key=lambda x: x["published"], reverse=True)
    enriched = {r["id"] for r in reviews}
    ratings = load("ratings.json", {})
    artists = load("artists.json", {})
    sp = load("specials.json", {})
    lists = specials.badges(sp)
    notes = load("notes.json", {})
    briefs = load("briefs.json", {})
    albums = load("albums.json", {})
    (OUT / "wtb.json").write_text(json.dumps([{k: r[k] for k in ("artist", "video_id", "date")} for r in sp.get("rankings", [])],
                                             ensure_ascii=False))  # the bot's artist lists link the "worst to best" video
    (OUT / "rt").mkdir(exist_ok=True)
    for a in by_id.values():
        rt = ratings.get(a["id"])
        li = lists.get(a["id"])
        nt = notes.get(a["id"])
        br = briefs.get(a["id"])
        html_ = (release_page(a, rt, artists.get((a.get("artist") or {}).get("mbid") or ""), li, nt, br) if a["id"] in enriched
                 else archive_page(a, by_artist[slug(a["artist_name"])], rt, li, nt, br, albums.get(a["id"]) or None))
        (OUT / "r" / f"{a['id']}.html").write_text(html_)
        crit, sales = critics_parts(rt)
        nt = nt or {}
        bf = (a.get("ai") or {}).get("brief") or (br or {}).get("brief")
        bm = (br or {}).get("moods") if not (a.get("ai") or {}).get("moods") else None  # the bot's mood vote for archive cards
        if crit or sales or li or nt or bf or bm:  # small per-review file for the bot's cards, so the Worker never parses all of ratings.json
            (OUT / "rt" / f"{a['id']}.json").write_text(json.dumps(
                {"crit": crit[:4], "sales": sales[:4], "wp_url": (rt or {}).get("wp_url"), "contested": contested(a, rt),
                 **({"lists": li[:4]} if li else {}), **({"blurb": nt["blurb"]} if nt.get("blurb") else {}),
                 **({"brief": bf} if bf else {}), **({"moods": bm} if bm else {}),
                 **({"fav": [f["t"] for f in nt["fav"]], "fav_play": any(f.get("dz") or f.get("am") for f in nt["fav"])} if nt.get("fav") else {})},
                ensure_ascii=False))
    for k, items in by_artist.items():
        (OUT / "a" / f"{k}.html").write_text(artist_page(items[0]["artist_name"], items))
    cat = sorted((catalog_entry(a) for a in by_id.values()), key=lambda x: x["d"], reverse=True)
    (OUT / "catalog.json").write_text(json.dumps(cat, ensure_ascii=False, separators=(",", ":")))
    recent = card.recent(reviews)
    items = "".join(recent_item(r) for r in recent)
    body = f"""<section class="intro"><h1>Обзоры Фантано без лишних кликов</h1>
<p>Оценки Anthony Fantano, жанры и где послушать. {reviews_word(len(cat))} с 2010 года.</p></section>
<h2 id="fresh">Свежее за 60 дней</h2><ul id="recent" class="list rows">{items or '<li>Пока пусто.</li>'}</ul>
<h2 id="catalog-h">Каталог</h2>
<div class="filters" id="search">
<input id="q" type="search" placeholder="Артист или альбом" autocomplete="off" enterkeyhint="search" aria-label="Поиск по артисту и альбому">
<div class="selects">
<select id="fscore" aria-label="Оценка"><option value="">Любая оценка</option><option value="8">от 8</option><option value="7">от 7</option><option value="5">от 5</option><option value="red">красные</option></select>
<select id="fgenre" aria-label="Жанр"><option value="">Любой жанр</option></select>
<select id="fyear" aria-label="Год обзора"><option value="">Любой год обзора</option></select>
<select id="fsort" aria-label="Сортировка"><option value="new">Сначала новые</option><option value="score">Сначала высокие оценки</option></select>
</div>
<label class="hide" hidden><input id="fhide" type="checkbox" checked> скрыть прослушанное</label>
</div>
<p id="count" class="muted" aria-live="polite"></p>
<ul id="catalog" class="list rows"></ul><button id="more" class="more" hidden>Показать ещё</button>"""
    (OUT / "index.html").write_text(page("Laziest Music Nerd — обзоры Фантано", body))
    print(f"site: {len(by_id)} release pages ({len(reviews)} with a full card), {len(by_artist)} artist pages")


if __name__ == "__main__":
    build()
