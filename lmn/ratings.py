"""Critic ratings, chart peaks and certifications for reviewed albums, from English Wikipedia.

Source: the album article's "Professional ratings" box ({{Album ratings}}), {{Album chart}} rows and
{{Certification Table Entry}} rows, read through the Wikipedia API. Wikipedia text is CC BY-SA 4.0;
scores and chart peaks are facts, and every place that shows them links the article ("по данным Википедии").
Pitchfork / Metacritic / Album of the Year pages are never fetched: their terms cover scrapers, and
Wikipedia already carries Pitchfork in ~80% and Metacritic in ~75% of its ratings boxes (probe 2026-11-01).

Writes data/ratings.json: {review_id: entry}. Run: python -m lmn.ratings  (env RATINGS_LIMIT, DATA_DIR).
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lmn.http import get_json

DATA = Path(os.environ.get("DATA_DIR", "data"))
WP_API = "https://en.wikipedia.org/w/api.php"
WP_PAGE = "https://en.wikipedia.org/wiki/"

# Shown first-available in this order, at most SHOW of them. Ordered by how often each outlet appears in
# Wikipedia ratings boxes of Fantano-reviewed albums (probe 2026-11-01, 159 boxes): Pitchfork 82%,
# AllMusic 79%, NME 48%, Rolling Stone 35%, The Guardian 33%, Clash 25% (most of it since 2020), ...
PRIORITY = ["Pitchfork", "AllMusic", "NME", "Rolling Stone", "The Guardian", "Clash", "Exclaim!", "The A.V. Club",
            "Spin", "The Independent", "The Line of Best Fit", "Paste", "Uncut", "Mojo", "Entertainment Weekly",
            "Slant Magazine", "Consequence", "PopMatters", "The Observer", "musicOMH", "DIY", "HipHopDX", "XXL",
            "Beats Per Minute", "Kerrang!", "Metal Hammer", "The Quietus", "Resident Advisor", "Under the Radar",
            "The Daily Telegraph", "The Times", "Q", "Record Collector", "Sputnikmusic"]
SHOW = 5  # on a Telegram card
KEEP = 8  # stored, one a line on the site
VERSION = 2  # what an entry holds (2: each review's link, mc_url). Older entries are not re-read on purpose (Daniil,
# 2026-11-01: the outlet's home page is enough); they get the links at their ordinary re-check.
# Home pages, the link when Wikipedia doesn't cite the review itself (the site's critics list)
HOME = {"Pitchfork": "https://pitchfork.com", "AllMusic": "https://www.allmusic.com", "NME": "https://www.nme.com",
        "Rolling Stone": "https://www.rollingstone.com", "The Guardian": "https://www.theguardian.com",
        "Clash": "https://www.clashmusic.com", "Exclaim!": "https://exclaim.ca", "The A.V. Club": "https://www.avclub.com",
        "Spin": "https://www.spin.com", "The Independent": "https://www.independent.co.uk",
        "The Line of Best Fit": "https://www.thelineofbestfit.com", "Paste": "https://www.pastemagazine.com",
        "Uncut": "https://www.uncut.co.uk", "Mojo": "https://www.mojo4music.com", "Entertainment Weekly": "https://ew.com",
        "Slant Magazine": "https://www.slantmagazine.com", "Consequence": "https://consequence.net",
        "PopMatters": "https://www.popmatters.com", "The Observer": "https://www.theguardian.com/observer",
        "musicOMH": "https://www.musicomh.com", "DIY": "https://diymag.com", "HipHopDX": "https://hiphopdx.com",
        "XXL": "https://www.xxlmag.com", "Beats Per Minute": "https://beatsperminute.com", "Kerrang!": "https://www.kerrang.com",
        "Metal Hammer": "https://www.loudersound.com/metal-hammer", "The Quietus": "https://thequietus.com",
        "Resident Advisor": "https://ra.co", "Under the Radar": "https://www.undertheradarmag.com",
        "The Daily Telegraph": "https://www.telegraph.co.uk", "The Times": "https://www.thetimes.com",
        "Record Collector": "https://recordcollectormag.com", "Sputnikmusic": "https://www.sputnikmusic.com",
        "Metacritic": "https://www.metacritic.com"}
ALIASES = {"pitchfork media": "Pitchfork", "consequence of sound": "Consequence", "slant": "Slant Magazine",
           "the av club": "The A.V. Club", "a.v. club": "The A.V. Club", "the guardian": "The Guardian",
           "guardian": "The Guardian", "the telegraph": "The Daily Telegraph", "allmusic": "AllMusic",
           "nme": "NME", "musicomh": "musicOMH", "exclaim!": "Exclaim!", "the line of best fit": "The Line of Best Fit",
           "q": "Q", "spin": "Spin", "diy": "DIY", "mojo": "Mojo", "uncut": "Uncut", "clash": "Clash",
           "paste": "Paste", "xxl": "XXL", "popmatters": "PopMatters", "hiphopdx": "HipHopDX"}
NOT_CRITICS = ("needle drop", "fantano")  # Fantano himself sometimes appears in the box

CHARTS = {"billboard200": "US", "uk2": "UK"}
REGIONS = {"united states": "US", "united kingdom": "UK", "canada": "CA", "australia": "AU", "germany": "DE",
           "france": "FR", "japan": "JP", "new zealand": "NZ", "netherlands": "NL", "sweden": "SE",
           "denmark": "DK", "norway": "NO", "poland": "PL", "brazil": "BR", "mexico": "MX", "italy": "IT",
           "spain": "ES", "belgium": "BE", "austria": "AT", "switzerland": "CH", "ireland": "IE"}
GRADES = {"A+": 10, "A": 9.5, "A−": 9, "A-": 9, "B+": 8.5, "B": 8, "B−": 7.5, "B-": 7.5, "C+": 7, "C": 6.5,
          "C−": 6, "C-": 6, "D+": 5, "D": 4, "D−": 3, "D-": 3, "E": 2, "F": 1}


# ---------- matching ----------

def norm(s):
    s = (s or "").replace("$", "s")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]", "", s)


def clean_album(artist, album):
    """Album title as Wikipedia would name it, or None for things that are not albums (track reviews)."""
    a = re.sub(r"\s*‡.*$", "", album or "")
    a = re.sub(r"\s*\((classic )?review\)\s*$", "", a, flags=re.I)
    a = re.sub(r"\s+review\s*$", "", a, flags=re.I).strip()
    if re.fullmatch(r"[\"“].*[\"”]", a):  # "Song" = a track review
        return None
    if norm(a) in ("selftitled", "st"):
        return artist
    return a or None


def template(text, names):
    """First {{name ...}} template (balanced braces) in wikitext, or None."""
    low = text.lower()
    best = None
    for n in names:
        m = re.search(r"\{\{\s*" + re.escape(n).replace(r"\ ", r"[ _]") + r"\s*[|}]", low)
        if m and (best is None or m.start() < best):
            best = m.start()
    if best is None:
        return None
    depth, j = 0, best
    while j < len(text) - 1:
        two = text[j:j + 2]
        if two == "{{":
            depth += 1
            j += 2
        elif two == "}}":
            depth -= 1
            j += 2
            if depth == 0:
                return text[best:j]
        else:
            j += 1
    return None


def params(t):
    """Template parameters: named ones lower-cased, positional ones as "1", "2", ..."""
    body = t[2:-2]
    parts, depth, cur, i = [], 0, "", 0
    while i < len(body):
        two = body[i:i + 2]
        if two in ("{{", "[["):
            depth += 1
            cur += two
            i += 2
        elif two in ("}}", "]]"):
            depth -= 1
            cur += two
            i += 2
        elif body[i] == "|" and depth == 0:
            parts.append(cur)
            cur = ""
            i += 1
        else:
            cur += body[i]
            i += 1
    parts.append(cur)
    out, pos = {}, 0
    for p in parts[1:]:
        k, eq, v = p.partition("=")
        if eq and re.fullmatch(r"\s*[\w ?-]+\s*", k):
            out[k.strip().lower()] = v.strip()
        else:
            pos += 1
            out[str(pos)] = p.strip()
    return out


def clean(v):
    v = re.sub(r"<ref[^>]*/>", "", v or "")
    v = re.sub(r"<ref.*?</ref>", "", v, flags=re.S)
    v = re.sub(r"<!--.*?-->", "", v, flags=re.S)
    m = re.search(r"\{\{\s*rating\s*\|\s*(\d+(?:\.\d+)?)\.?\s*\|\s*(\d+(?:\.\d+)?)", v, re.I)
    if m:
        return f"{fmt(float(m.group(1)))}/{fmt(float(m.group(2)))}"
    v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", v)
    v = re.sub(r"\{\{[^{}]*\}\}", "", v)
    v = v.replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", v).strip(" ()")


def named_refs(text):
    """{ref name: the URL it cites}: a box often reuses a reference defined in the article body (<ref name="AM"/>)."""
    out = {}
    for m in re.finditer(r"<ref\s+name\s*=\s*\"?([^\"/>]+?)\"?\s*>(.*?)</ref>", text or "", re.S | re.I):
        url = cited_url(m.group(2))
        if url:
            out.setdefault(m.group(1).strip(), url)
    return out


def cited_url(v):
    """The URL a citation points to: a cite template's url= (not archive-url=), else a bare [http… title] link."""
    m = re.search(r"\|\s*url\s*=\s*(https?://[^|}\s<]+)", v or "", re.I) or re.search(r"\[(https?://[^\s\]<]+)", v or "")
    return m.group(1) if m else None


def review_url(v, refs):
    """The link to the review behind one score in the ratings box: its own <ref>, a named one from the body, or a bare link.
    None when Wikipedia gives no source for it."""
    for m in re.finditer(r"<ref([^>]*?)(/?)>(?:(.*?)</ref>)?", v or "", re.S | re.I):
        if m.group(3):
            url = cited_url(m.group(3))
        else:
            nm = re.search(r"name\s*=\s*\"?([^\"/>]+?)\"?\s*$", m.group(1).strip(), re.I)
            url = refs.get(nm.group(1).strip()) if nm else None
        if url:
            return url
    m = re.search(r"\[(https?://[^\s\]<]+)", re.sub(r"<ref.*?</ref>", "", v or "", flags=re.S))
    return m.group(1) if m else None


def fmt(x):
    return str(int(x)) if x == int(x) else str(x)


def find_article(artist, album):
    """(title, wikitext, revid) of the English Wikipedia article about this album, or (None, None, None).

    Accepted only when the article's album infobox names the same album and the same artist."""
    na, nal = norm(artist), norm(album)
    if not nal:
        return None, None, None
    for q in (f"{album} {artist} album", f'intitle:"{album}" album'):
        d = get_json(WP_API + "?" + urllib.parse.urlencode({
            "action": "query", "format": "json", "formatversion": "2", "generator": "search", "gsrsearch": q,
            "gsrlimit": "5", "prop": "revisions", "rvprop": "content|ids", "rvslots": "main", "maxlag": "5"}))
        for p in sorted(d.get("query", {}).get("pages", []), key=lambda p: p.get("index", 99)):
            try:
                rev = p["revisions"][0]
                text = rev["slots"]["main"]["content"]
            except (KeyError, IndexError):
                continue
            ib = template(text, ["infobox album", "infobox mixtape", "infobox ep"])
            if not ib:
                continue
            prm = params(ib)
            plain_title = norm(re.sub(r"\s*\(.*\)$", "", p["title"]))
            names = {norm(clean(prm.get("name", ""))), plain_title}
            art = norm(clean(prm.get("artist", "")))
            if nal in names and art and na and (na in art or art in na):
                return p["title"], text, rev.get("revid")
        time.sleep(0.5)
    return None, None, None


# ---------- parsing ----------

def outlet_name(raw):
    name = clean(raw)
    key = name.lower().strip()
    if key in ALIASES:
        return ALIASES[key]
    for p in PRIORITY:
        if p.lower() == key:
            return p
    return name


def to10(score):
    """A score on a 0-10 scale, or None for words like "favorable"."""
    s = score.replace(",", ".").strip()
    m = re.fullmatch(r"([\d.]+)\s*%", s)
    if m:
        return round(float(m.group(1)) / 10, 1) if float(m.group(1)) <= 100 else None
    m = re.fullmatch(r"([\d.]+)\s*/\s*([\d.]+)", s)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return round(10 * a / b, 1) if b and a <= b else None
    if s in GRADES:
        return GRADES[s]
    return None


def parse(text):
    """Everything this module takes from one article's wikitext."""
    out = {"critics": [], "metacritic": None, "adm": None, "charts": {}, "certs": []}
    box = template(text, ["album ratings", "music ratings"])
    if box:
        prm = params(box)
        refs = named_refs(text)
        nums = sorted(int(k[3:]) for k in prm if re.fullmatch(r"rev\d+", k))
        seen = set()
        for n in nums:
            name = outlet_name(prm[f"rev{n}"])
            score = clean(prm.get(f"rev{n}score", ""))
            if not name or not score or any(x in name.lower() for x in NOT_CRITICS) or name in seen:
                continue
            seen.add(name)
            c = {"outlet": name, "score": score, "s10": to10(score)}
            url = review_url(prm.get(f"rev{n}score", "") + " " + prm[f"rev{n}"], refs)
            if url:
                c["url"] = url
            out["critics"].append(c)
        aggs = {k: clean(v) for k, v in prm.items()}
        mc_raw = prm.get("mc", "")
        for i in range(1, 6):  # newer boxes: aggregate1 = "AnyDecentMusic?", aggregate1score = "7.6/10"
            label = aggs.get(f"aggregate{i}", "").lower()
            if "metacritic" in label:
                aggs["mc"] = aggs.get(f"aggregate{i}score", "")
                mc_raw = prm.get(f"aggregate{i}score", "")
            elif "decent" in label:
                aggs["adm"] = aggs.get(f"aggregate{i}score", "")
        m = re.match(r"(\d{1,3})\s*/\s*100", aggs.get("mc", ""))
        if m:
            out["metacritic"] = int(m.group(1))
            url = review_url(mc_raw, refs)
            if url:
                out["mc_url"] = url
        m = re.match(r"(\d+(?:\.\d)?)\s*/\s*10\b", aggs.get("adm", ""))
        if m:
            out["adm"] = float(m.group(1))
    for t in re.finditer(r"\{\{\s*album ?chart\s*\|([^{}]*)\}\}", text, re.I):
        prm = params("{{x|" + t.group(1) + "}}")
        key = CHARTS.get(prm.get("1", "").strip().lower())
        if key and prm.get("2", "").strip().isdigit():
            peak = int(prm["2"])
            out["charts"][key] = min(peak, out["charts"].get(key, peak))
    for t in re.finditer(r"\{\{\s*certification table entry", text, re.I):
        whole = template(text[t.start():], ["certification table entry"])
        if not whole:
            continue
        prm = params(whole)
        region = REGIONS.get(clean(prm.get("region", "")).lower())
        award = clean(prm.get("award", ""))
        mult = clean(prm.get("number", ""))
        sales = clean(prm.get("salesamount", ""))
        if not region or not (award or sales):
            continue
        c = {"region": region, "award": (f"{mult}× " if mult.isdigit() and mult != "1" else "") + award}
        if sales:
            c["sales"] = sales
        out["certs"].append(c)
    return out


def summarize(p):
    """What the card / site shows: up to KEEP critics in PRIORITY order, plus an average for the "спорно" mark."""
    rank = {name: i for i, name in enumerate(PRIORITY)}
    critics = sorted(p["critics"], key=lambda c: rank.get(c["outlet"], len(rank)))
    # only real scores are shown: "Positive" / "favorable" are words, not ratings
    shown = [c for c in critics if c["outlet"] in rank and c["s10"] is not None][:KEEP]
    nums = [c["s10"] for c in p["critics"] if c["s10"] is not None]
    if p["metacritic"] is not None:
        avg, n = round(p["metacritic"] / 10, 1), None
    elif len(nums) >= 3:
        avg, n = round(sum(nums) / len(nums), 1), len(nums)
    else:
        avg, n = None, None
    return {"v": VERSION, "metacritic": p["metacritic"], **({"mc_url": p["mc_url"]} if p.get("mc_url") else {}), "adm": p["adm"], "critics": shown, "critics_total": len(p["critics"]),
            "critic_avg10": avg, "critic_avg_n": n, "charts": p["charts"], "certs": p["certs"][:6]}


def card_line(e, n=SHOW):
    """One plain-text line for a Telegram card (Metacritic + up to n critics), or "" when there is nothing to show."""
    if not e or not e.get("wp"):
        return ""
    bits = []
    if e.get("metacritic") is not None:
        bits.append(f"Metacritic {e['metacritic']}")
    bits += [f"{c['outlet']} {c['score']}" for c in e.get("critics", [])[:n]]
    return "Критики: " + " · ".join(bits) if bits else ""


def sales_line(e):
    if not e or not e.get("wp"):
        return ""
    bits = [f"{k} #{v}" for k, v in sorted(e.get("charts", {}).items(), key=lambda kv: kv[0] != "US")]
    bits += [f"{c['region']} {c['award'] or c['sales']}" for c in e.get("certs", [])[:3]]
    return "Чарты и сертификаты: " + " · ".join(bits) if bits else ""


# ---------- schedule ----------

def due(entry, published, now):
    """Ratings boxes fill in over weeks after release, so young reviews are re-checked more often."""
    if not entry:
        return True
    age = (now - published).days
    checked = datetime.fromisoformat(entry["checked"])
    since = (now - checked).days
    if age <= 21:
        return since >= 1
    if age <= 90:
        return since >= 7
    return since >= (90 if entry.get("wp") else 180)


def save(path, store):
    # one review per line: small diffs in the daily commit
    lines = [json.dumps(k) + ": " + json.dumps(store[k], ensure_ascii=False, separators=(",", ":")) for k in sorted(store)]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("{\n" + ",\n".join(lines) + "\n}\n")
    tmp.replace(path)


def run():
    limit = int(os.environ.get("RATINGS_LIMIT", "400"))
    now = datetime.now(timezone.utc)
    path = DATA / "ratings.json"
    store = json.loads(path.read_text()) if path.exists() else {}
    items = {}
    for name in ("archive.json", "reviews.json"):
        p = DATA / name
        for r in json.loads(p.read_text()) if p.exists() else []:
            items[r["id"]] = r
    todo = sorted((r for r in items.values()), key=lambda r: r["published"], reverse=True)
    done = found = 0
    for r in todo:
        if done >= limit:
            break
        pub = datetime.fromisoformat(r["published"])
        if not due(store.get(r["id"]), pub, now):
            continue
        album = None if r.get("track") else clean_album(r.get("artist_name"), r.get("album"))
        entry = {"checked": now.isoformat(timespec="seconds"), "wp": None}
        if album and r.get("artist_name"):
            try:
                title, text, revid = find_article(r["artist_name"], album)
            except Exception as ex:  # a network error must not stop the whole batch or wipe old data
                print(f"  ! {r['artist_name']} — {album}: {str(ex)[:80]}", file=sys.stderr)
                done += 1
                continue
            if title:
                entry.update(wp=title, wp_url=WP_PAGE + urllib.parse.quote(title.replace(" ", "_")), revid=revid)
                try:
                    entry.update(summarize(parse(text)))
                except Exception as ex:  # odd wikitext in one article must not stop the batch
                    print(f"  ! parse {title}: {ex!r}"[:120], file=sys.stderr)
                found += 1
        old = store.get(r["id"]) or {}
        if old.get("wp") and not entry["wp"]:
            entry = dict(old, checked=entry["checked"])  # keep what we had; search can miss on a bad day
        store[r["id"]] = entry
        done += 1
        if done % 100 == 0:  # a timeout or crash later in the batch keeps what was already found
            save(path, store)
        time.sleep(0.5)
    save(path, store)
    with_c = sum(1 for e in store.values() if e.get("critics") or e.get("metacritic") is not None)
    print(f"ratings: checked {done}, article found {found}; stored {len(store)}, with critic scores {with_c}")


if __name__ == "__main__":
    run()
