"""Build the static site (GitHub Pages) from data/*.json into _site/."""
import hashlib
import html
import json
import os
import shutil
import unicodedata
import urllib.parse
from pathlib import Path

from . import card, tnd
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


def page(title, body, depth=0):
    up = "../" * depth
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title><link rel="stylesheet" href="{up}style.css"><link rel="manifest" href="{up}manifest.json">
<meta name="theme-color" content="#16161a"><link rel="icon" href="{up}icon.svg"><link rel="apple-touch-icon" href="{up}apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="LMN"></head>
<body><header><a class="logo" href="{up}index.html">Laziest Music Nerd</a><span id="login"></span></header>
<main>{body}</main>
<footer>{e(DISCLAIMER)}</footer>
<script>window.LMN={{root:"{up}",worker:{json.dumps(worker_url())},bot:"laziest_music_nerd_bot"}}</script>
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
    return [("🔎 YouTube Music", f"https://music.youtube.com/search?q={q}"), ("🔎 Google", f"https://www.google.com/search?q={q}")]


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


def archive_page(a, artist_reviews, rt=None):
    """A release page for a review the bot never posted a card for: what the archive knows, the artist's other
    reviews, and the reader's marks."""
    review = f"https://youtu.be/{a['video_id']}" if a.get("video_id") else a["url"]
    btns = [("▶ Видеообзор" if a.get("video_id") else "Обзор", review)]
    if a.get("video_id") and "theneedledrop.com" in a["url"]:
        btns.append(("Текст обзора на TND", a["url"]))
    btns += search_buttons(a["artist_name"], a["album"])
    meta = " · ".join(x for x in [", ".join((a.get("genres") or [])[:5]), "обзор " + a["published"][:10],
                                    "гостевой обзор" if a.get("guest") else None] if x)
    others = [x for x in artist_reviews if x["id"] != a["id"]]
    hist = (f'<h2>Фантано об этом артисте</h2>{history_list(artist_reviews, a["id"], 1)}' if others else "")
    rows = critics_rows(rt, a)
    dl = f"<dl>{''.join(f'<dt>{k}</dt><dd>{v}</dd>' for k, v in rows)}</dl>" if rows else ""
    body = f"""<article class="release" data-id="{e(a['id'])}">
<h1><a href="../a/{slug(a['artist_name'])}.html">{e(a['artist_name'])}</a> — {e(a['album'])}</h1>
<p>{score_badge(a)} <span class="muted">{e(meta)}</span></p>
{dl}
<p class="btns">{''.join(f'<a class="btn" href="{e(u)}">{e(n)}</a>' for n, u in btns)}</p>
<div class="mine" hidden></div>
<p class="avg muted"></p>
{hist}
</article>"""
    return page(f"{a['artist_name']} — {a['album']}", body, depth=1)


def artist_page(name, items):
    n = len(items)
    word = "обзор" if n % 10 == 1 and n % 100 != 11 else "обзора" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "обзоров"
    body = f"""<h1>{e(name)}</h1>
<p class="muted">{n} {word} Фантано</p>
{history_list(items, None, 1)}"""
    return page(name, body, depth=1)


def release_page(r, rt=None):
    c = color(r.get("score"), r.get("not_good"), r.get("classic"))
    a = r.get("artist") or {}
    ai = r.get("ai") or {}
    rows = []
    if ai.get("who"):
        rows.append(("Кто", e(ai["who"])))
    before = card.fantano_before(r)
    if before:
        rows.append(("Фантано раньше", before))
    if ai.get("brief"):
        rows.append(("Бриф", e(ai["brief"])))
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
    if r.get("tracks"):
        rows.append(("Треклист", "<ol>" + "".join(f"<li>{line.split('. ', 1)[1]}</li>" for line in card.tracklist(r)) + "</ol>"
                     + ('<span class="muted">★ — выделил Фантано</span>' if (r.get("ai") or {}).get("best_tracks") else "")))
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
    (OUT / "rt").mkdir(exist_ok=True)
    for a in by_id.values():
        rt = ratings.get(a["id"])
        html_ = release_page(a, rt) if a["id"] in enriched else archive_page(a, by_artist[slug(a["artist_name"])], rt)
        (OUT / "r" / f"{a['id']}.html").write_text(html_)
        crit, sales = critics_parts(rt)
        if crit or sales:  # small per-review file for the bot's cards, so the Worker never parses all of ratings.json
            (OUT / "rt" / f"{a['id']}.json").write_text(json.dumps(
                {"crit": crit[:4], "sales": sales[:4], "wp_url": rt.get("wp_url"), "contested": contested(a, rt)}, ensure_ascii=False))
    for k, items in by_artist.items():
        (OUT / "a" / f"{k}.html").write_text(artist_page(items[0]["artist_name"], items))
    cat = sorted((catalog_entry(a) for a in by_id.values()), key=lambda x: x["d"], reverse=True)
    (OUT / "catalog.json").write_text(json.dumps(cat, ensure_ascii=False, separators=(",", ":")))
    recent = card.recent(reviews)
    items = "".join(recent_item(r) for r in recent)
    body = f"""<h2>Свежее за 60 дней</h2><ul class="list">{items or '<li>Пока пусто.</li>'}</ul>
<h2>Каталог</h2>
<div class="filters">
<input id="q" type="search" placeholder="Артист или альбом">
<select id="fscore"><option value="">Любая оценка</option><option value="8">от 8</option><option value="7">от 7</option><option value="5">от 5</option><option value="red">красные</option></select>
<select id="fgenre"><option value="">Любой жанр</option></select>
<select id="fyear"><option value="">Любой год обзора</option></select>
<select id="fsort"><option value="new">Сначала новые</option><option value="score">Сначала высокие оценки</option></select>
<label><input id="fhide" type="checkbox" checked> скрыть прослушанное</label>
</div>
<ul id="catalog" class="list"></ul><button id="more" hidden>Показать ещё</button>"""
    (OUT / "index.html").write_text(page("Laziest Music Nerd — обзоры Фантано", body))
    print(f"site: {len(by_id)} release pages ({len(reviews)} with a full card), {len(by_artist)} artist pages")


if __name__ == "__main__":
    build()
