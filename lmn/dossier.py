"""Artist dossier from Wikipedia (spec, second version: "Полное досье"): the article's first paragraph and the
band's members. Only for artists with a MusicBrainz ID (the reviews the bot posted a card for), found through
MusicBrainz -> Wikidata -> Wikipedia, so the article is always the artist's own and never a namesake's.
The Russian article is used when there is one, else the English one.

Writes data/artists.json, one artist per line: {mbid: {checked, lang, title, url, extract, members, past_members}}
(only checked when no article was found). Re-checked every 30 days.

Run: python -m lmn.dossier (workflow "Досье артистов")."""
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import http, musicbrainz
from .ratings import clean, params, template

DATA = Path(os.environ.get("DATA_DIR", "data"))
RECHECK = timedelta(days=30)
EXTRACT_MAX = 600
# infobox parameter names for current and past members, English and Russian Wikipedia
MEMBERS = ("current_members", "members", "состав")
PAST = ("past_members", "former_members", "бывшие участники", "бывшие_участники")


def wikidata_id(mbid):
    d = musicbrainz._get(f"artist/{mbid}", inc="url-rels")
    for rel in d.get("relations") or []:
        m = re.search(r"wikidata\.org/wiki/(Q\d+)", (rel.get("url") or {}).get("resource", ""))
        if rel.get("type") == "wikidata" and m:
            return m.group(1)
    return None


def article(qid):
    """(lang, title) of the artist's Wikipedia article, Russian first."""
    d = http.get_json(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
    links = ((d.get("entities") or {}).get(qid) or {}).get("sitelinks") or {}
    for lang in ("ru", "en"):
        if links.get(f"{lang}wiki"):
            return lang, links[f"{lang}wiki"]["title"]
    return None, None


def member_list(v):
    """Names from an infobox value: '{{flatlist|* [[A]] * [[B]]}}', 'A<br>B', '{{hlist|A|B}}', and Russian
    '{{нп3|Досс, Билл|Билл Досс|en|Bill Doss}}' (the name as shown is the second parameter)."""
    v = re.sub(r"<ref[^>]*/>|<ref.*?</ref>|<!--.*?-->", "", v or "", flags=re.S)
    v = re.sub(r"\{\{\s*(?:нп\d?|не переведено \d?)\s*\|([^|}]*)(?:\|([^|}]*))?[^{}]*\}\}",
               lambda m: (m.group(2) or m.group(1)).strip(), v, flags=re.I)
    v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", v)  # links: the text shown
    v = re.sub(r"\(\s*[\d–—-]+[^)]*\)", "", v)  # years in brackets: "(1985–present)"
    v = re.sub(r"<br\s*/?>", "\n", v, flags=re.I)
    v = re.sub(r"\{\{\s*(?:flat|plain|unbulleted|hlist|bulleted)\s*list\s*\||\{\{\s*hlist\s*\|", "\n", v, flags=re.I)
    names = []
    for part in re.split(r"[\n*•·|]|,", v):
        n = clean(part).strip(" ,;{}")
        if n and len(n) <= 60 and not re.search(r"[{}\[\]=]", n) and n not in names:
            names.append(n)
    return names[:12]


def members(text):
    box = template(text or "", ["infobox musical artist", "музыкальный коллектив", "музыкант"])
    if not box:
        return [], []
    prm = params(box)
    cur = next((member_list(prm[k]) for k in MEMBERS if prm.get(k)), [])
    past = next((member_list(prm[k]) for k in PAST if prm.get(k)), [])
    return cur, [m for m in past if m not in cur]  # some articles list a member in both


def first_paragraph(extract):
    p = (extract or "").strip().split("\n")[0]
    if len(p) <= EXTRACT_MAX:
        return p
    cut = p[:EXTRACT_MAX]
    return cut[:cut.rfind(". ") + 1] if ". " in cut else cut.rstrip() + "…"


def lookup(mbid):
    qid = wikidata_id(mbid)
    if not qid:
        return {}
    lang, title = article(qid)
    if not title:
        return {}
    quoted = urllib.parse.quote(title.replace(" ", "_"))
    s = http.get_json(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quoted}")
    w = http.get_json(f"https://{lang}.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "format": "json", "formatversion": "2", "prop": "revisions", "rvprop": "content",
        "rvslots": "main", "titles": title}))
    try:
        text = w["query"]["pages"][0]["revisions"][0]["slots"]["main"]["content"]
    except (KeyError, IndexError):
        text = ""
    cur, past = members(text)
    return {"lang": lang, "title": title, "url": f"https://{lang}.wikipedia.org/wiki/{quoted}",
            "extract": first_paragraph(s.get("extract")), "members": cur, "past_members": past}


def run():
    limit = int(os.environ.get("DOSSIER_LIMIT", "200"))
    now = datetime.now(timezone.utc)
    path = DATA / "artists.json"
    store = json.loads(path.read_text()) if path.exists() else {}
    reviews = json.loads((DATA / "reviews.json").read_text()) if (DATA / "reviews.json").exists() else []
    mbids = []
    for r in sorted(reviews, key=lambda r: r["published"], reverse=True):
        m = (r.get("artist") or {}).get("mbid")
        if m and m not in mbids:
            mbids.append(m)
    done = found = 0
    for m in mbids:
        if done >= limit:
            break
        old = store.get(m)
        if old and now - datetime.fromisoformat(old["checked"]) < RECHECK:
            continue
        try:
            entry = lookup(m)
        except Exception as ex:  # one artist's failure must not stop the batch or wipe what we had
            print(f"  ! {m}: {type(ex).__name__} {str(ex)[:80]}", file=sys.stderr)
            done += 1
            continue
        if not entry and old and old.get("title"):
            entry = {k: v for k, v in old.items() if k != "checked"}  # keep what we had; a lookup can miss on a bad day
        store[m] = {"checked": now.isoformat(timespec="seconds"), **entry}
        found += bool(entry)
        done += 1
        time.sleep(0.3)
    lines = [json.dumps(k) + ": " + json.dumps(store[k], ensure_ascii=False, separators=(",", ":")) for k in sorted(store)]
    path.write_text("{\n" + ",\n".join(lines) + "\n}\n")
    print(f"dossier: checked {done}, article found {found}; stored {len(store)}")


if __name__ == "__main__":
    run()
