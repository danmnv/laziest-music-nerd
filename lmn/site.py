"""Build the static site (GitHub Pages) from data/*.json into _site/."""
import html
import json
import os
import shutil
from pathlib import Path

from . import card
from .colors import color, label

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
<meta name="theme-color" content="#16161a"><link rel="icon" href="{up}icon.svg"></head>
<body><header><a class="logo" href="{up}index.html">Laziest Music Nerd</a><span id="login"></span></header>
<main>{body}</main>
<footer>{e(DISCLAIMER)}</footer>
<script>window.LMN={{root:"{up}",worker:{json.dumps(worker_url())},bot:"laziest_music_nerd_bot"}}</script>
<script src="{up}app.js"></script></body></html>"""


def worker_url():
    f = DATA / "worker_url.txt"
    return f.read_text().strip() if f.exists() else ""


def release_page(r):
    c = color(r.get("score"), r.get("not_good"), r.get("classic"))
    a = r.get("artist") or {}
    ai = r.get("ai") or {}
    links = r.get("links") or {}
    rows = []
    if ai.get("who"):
        rows.append(("Кто", e(ai["who"])))
    before = card.fantano_before(r)
    if before:
        rows.append(("Фантано раньше", before))
    if ai.get("brief"):
        rows.append(("Бриф", e(ai["brief"])))
    if ai.get("moods"):
        rows.append(("Похоже на", e(" / ".join(ai["moods"])) + ' <span class="muted">(предположение ИИ)</span>'))
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
    if r.get("previous"):
        hist = "".join(f'<li><a href="{e(p["url"])}">{e(p["album"])}</a> — {label(p.get("score"), p.get("not_good"), p.get("classic"), "?")} <span class="muted">{e(p["published"][:4])}</span></li>' for p in r["previous"])
        rows.append(("История оценок", f"<ul>{hist}</ul>"))
    btns = "".join(f'<a class="btn" href="{e(u)}">{n}</a>' for n, u in [
        ("Bandcamp", links.get("bandcamp")), ("YouTube Music", links.get("ytmusic")),
        ("Все платформы", links.get("songlink")), ("Оригинальный обзор", r["url"]),
        ("Видео", f"https://youtu.be/{r['video_id']}" if r.get("video_id") else None)] if u)
    meta = " · ".join(x for x in [", ".join(r.get("genres", [])[:5]), card.TYPE_RU.get(r.get("type")),
                                    f"{r['duration_min']} мин" if r.get("duration_min") else None, r["published"][:10],
                                    "гостевой обзор" if r.get("guest") else None] if x)
    cover = (r.get("covers") or [None])[0]
    body = f"""<article class="release" data-id="{e(r['id'])}">
{f'<img class="cover" src="{e(cover)}" alt="">' if cover else ''}
<h1>{e(r['artist_name'])} — {e(r['album'])}</h1>
<p><span class="score {c or 'none'}">{card.score_text(r)}</span> <span class="muted">{e(meta)}</span></p>
<dl>{''.join(f'<dt>{k}</dt><dd>{v}</dd>' for k, v in rows)}</dl>
<p class="btns">{btns}</p>
<div class="mine" hidden></div>
<p class="avg muted"></p>
</article>"""
    return page(f"{r['artist_name']} — {r['album']}", body, depth=1)


def catalog_entry(a, enriched):
    return {"i": a["id"], "a": a.get("artist_name") or "", "t": a.get("album") or "", "s": a.get("score"),
            "ng": 1 if a.get("not_good") else 0, "cl": 1 if a.get("classic") else 0, "d": a["published"][:10],
            "g": (a.get("genres") or [])[:4], "u": a["url"], "p": 1 if a["id"] in enriched else 0,
            "gu": 1 if a.get("guest") else 0}


def recent_item(r):
    c = color(r.get("score"), r.get("not_good"), r.get("classic")) or "none"
    extra = [(r.get("genres") or [None])[0], card.TYPE_RU.get(r.get("type")),
             f"{r['duration_min']} мин" if r.get("duration_min") else None]
    return (f'<li data-id="{e(r["id"])}"><span class="score {c}">{label(r.get("score"), r.get("not_good"), r.get("classic"))}</span> '
            f'<a href="r/{e(r["id"])}.html">{e(r["artist_name"])} — {e(r["album"])}</a>'
            f'<span class="muted"> {e(" · ".join(x for x in extra if x))}</span><span class="st"></span></li>')


def build():
    reviews = load("reviews.json", [])
    archive = load("archive.json", [])
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(SRC, OUT)
    (OUT / "r").mkdir(exist_ok=True)
    enriched = {r["id"] for r in reviews}
    by_id = {a["id"]: a for a in archive}
    for r in reviews:
        by_id[r["id"]] = r
        (OUT / "r" / f"{r['id']}.html").write_text(release_page(r))
    cat = sorted((catalog_entry(a, enriched) for a in by_id.values()), key=lambda x: x["d"], reverse=True)
    (OUT / "catalog.json").write_text(json.dumps(cat, ensure_ascii=False, separators=(",", ":")))
    recent = card.recent(reviews)
    items = "".join(recent_item(r) for r in recent)
    body = f"""<h2>Свежее за 60 дней</h2><ul class="list">{items or '<li>Пока пусто.</li>'}</ul>
<h2>Каталог</h2>
<div class="filters">
<input id="q" type="search" placeholder="Артист или альбом">
<select id="fscore"><option value="">Любая оценка</option><option value="8">от 8</option><option value="7">от 7</option><option value="5">от 5</option><option value="red">красные</option></select>
<select id="fgenre"><option value="">Любой жанр</option></select>
<select id="fyear"><option value="">Любой год</option></select>
<label><input id="fhide" type="checkbox" checked> скрыть прослушанное</label>
</div>
<ul id="catalog" class="list"></ul><button id="more" hidden>Показать ещё</button>"""
    (OUT / "index.html").write_text(page("Laziest Music Nerd — обзоры Фантано", body))
    print(f"site: {len(reviews)} release pages, {len(cat)} catalog entries")


if __name__ == "__main__":
    build()
