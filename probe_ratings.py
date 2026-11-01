"""Temporary probe: how many reviewed albums have critic ratings / charts / certifications in open sources.

Runs from GitHub Actions (the dev container can't reach these hosts). Read-only, polite (sequential,
pauses, project User-Agent). Sources: Wikipedia API (CC BY-SA), Wikidata (CC0), MusicBrainz (CC0).
Pitchfork / Metacritic / AOTY pages are NOT fetched; only their robots.txt and terms are checked.
"""
import collections
import json
import random
import re
import sys
import time
import unicodedata
import urllib.parse
from datetime import datetime, timezone

from lmn.http import get_json, request

WP = "https://en.wikipedia.org/w/api.php"
WD = "https://www.wikidata.org/w/api.php"
MB = "https://musicbrainz.org/ws/2"


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("&", "and")
    s = re.sub(r"\(.*?\)", "", s) if len(re.sub(r"\(.*?\)", "", s).strip()) > 2 else s
    return re.sub(r"[^a-z0-9]", "", s)


def template(text, names):
    low = text.lower()
    for n in names:
        i = low.find("{{" + n)
        if i < 0:
            continue
        depth, j = 0, i
        while j < len(text) - 1:
            if text[j:j + 2] == "{{":
                depth += 1
                j += 2
                continue
            if text[j:j + 2] == "}}":
                depth -= 1
                j += 2
                if depth == 0:
                    return text[i:j]
                continue
            j += 1
    return None


def split_params(t):
    t = t[2:-2]
    parts, depth, cur = [], 0, ""
    i = 0
    while i < len(t):
        two = t[i:i + 2]
        if two in ("{{", "[["):
            depth += 1
            cur += two
            i += 2
            continue
        if two in ("}}", "]]"):
            depth -= 1
            cur += two
            i += 2
            continue
        if t[i] == "|" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += t[i]
        i += 1
    parts.append(cur)
    out = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def clean(v):
    v = re.sub(r"<ref[^>]*/>", "", v)
    v = re.sub(r"<ref.*?</ref>", "", v, flags=re.S)
    v = re.sub(r"<!--.*?-->", "", v, flags=re.S)
    m = re.search(r"\{\{\s*rating\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)", v, re.I)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"\{\{[^{}]*\}\}", "", v)
    v = v.replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", v).strip()


def wiki_find(artist, album):
    q = f"{album} {artist} album"
    params = {"action": "query", "format": "json", "formatversion": "2", "generator": "search",
              "gsrsearch": q, "gsrlimit": "5", "prop": "revisions|pageprops", "rvprop": "content",
              "rvslots": "main", "ppprop": "wikibase_item", "maxlag": "5"}
    d = get_json(WP + "?" + urllib.parse.urlencode(params))
    pages = sorted(d.get("query", {}).get("pages", []), key=lambda p: p.get("index", 99))
    na, nal = norm(artist), norm(album)
    for p in pages:
        try:
            text = p["revisions"][0]["slots"]["main"]["content"]
        except (KeyError, IndexError):
            continue
        ib = template(text, ["infobox album", "infobox mixtape", "infobox ep"])
        if not ib:
            continue
        prm = split_params(ib)
        name = norm(clean(prm.get("name", ""))) or norm(re.sub(r"\(.*\)", "", p["title"]))
        art = norm(clean(prm.get("artist", "")))
        title_ok = name == nal or norm(re.sub(r"\(.*\)", "", p["title"])) == nal
        artist_ok = art and na and (na in art or art in na)
        if title_ok and artist_ok:
            return p["title"], text, p.get("pageprops", {}).get("wikibase_item")
    return None, None, None


def analyse_wikitext(text):
    r = {"outlets": {}, "aggregates": {}}
    t = template(text, ["album ratings", "music ratings", "album reviews"])
    if t:
        prm = split_params(t)
        for k, v in prm.items():
            m = re.fullmatch(r"rev(\d+)", k)
            if m:
                name = clean(v)
                score = clean(prm.get(f"rev{m.group(1)}score", ""))
                if name:
                    r["outlets"][name] = score
            elif k in ("mc", "adm", "aoty", "metacritic", "anydecentmusic", "anydecentmusic?") or not re.match(r"rev|title|width|state|subtitle|noprose|align|style", k):
                cv = clean(v)
                if cv:
                    r["aggregates"][k] = cv
    r["has_ratings_box"] = bool(t)
    r["chart_rows"] = len(re.findall(r"\{\{\s*album ?chart\s*\|", text, re.I))
    r["charts"] = sorted(set(m.lower() for m in re.findall(r"\{\{\s*album ?chart\s*\|\s*([^|}]+)", text, re.I)))
    certs = re.findall(r"\{\{\s*certification table entry(.*?)\}\}", text, re.I | re.S)
    r["cert_rows"] = len(certs)
    r["cert_regions"] = sorted(set(clean(m.group(1)).lower() for c in certs for m in [re.search(r"\|\s*region\s*=\s*([^|]+)", c)] if m))
    r["cert_awards"] = [clean(m.group(1)) for c in certs for m in [re.search(r"\|\s*award\s*=\s*([^|]+)", c)] if m]
    r["sales_amount"] = sum(1 for c in certs if re.search(r"\|\s*salesamount\s*=\s*\S", c))
    r["has_reception_section"] = bool(re.search(r"==\s*(critical )?reception\s*==", text, re.I))
    r["mentions_metacritic"] = "metacritic" in text.lower()
    return r


def wikidata(qids):
    out = {}
    qids = [q for q in qids if q]
    for i in range(0, len(qids), 50):
        d = get_json(WD + "?" + urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(qids[i:i + 50]),
                                                       "props": "claims", "format": "json"}))
        for q, e in d.get("entities", {}).items():
            cl = e.get("claims", {})
            by = []
            for s in cl.get("P444", []):
                for qq in s.get("qualifiers", {}).get("P447", []):
                    try:
                        by.append(qq["datavalue"]["value"]["id"])
                    except KeyError:
                        pass
            out[q] = {"p444": len(cl.get("P444", [])), "by": by, "metacritic_id": "P1712" in cl,
                      "aoty_id": "P7712" in cl or "P13066" in cl}
        time.sleep(1)
    return out


def labels(qids):
    lab = {}
    qids = list(qids)
    for i in range(0, len(qids), 50):
        d = get_json(WD + "?" + urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(qids[i:i + 50]),
                                                       "props": "labels", "languages": "en", "format": "json"}))
        for q, e in d.get("entities", {}).items():
            lab[q] = e.get("labels", {}).get("en", {}).get("value", q)
        time.sleep(1)
    return lab


def mb_lookup(artist, album, rgid=None):
    if not rgid:
        q = f'releasegroup:"{album}" AND artist:"{artist}"'
        d = get_json(f"{MB}/release-group?fmt=json&limit=1&query=" + urllib.parse.quote(q))
        time.sleep(1.1)
        rg = (d.get("release-groups") or [None])[0]
        if not rg or rg.get("score", 0) < 95:
            return None
        rgid = rg["id"]
    d = get_json(f"{MB}/release-group/{rgid}?fmt=json&inc=url-rels+ratings")
    time.sleep(1.1)
    types = collections.Counter(r.get("type") for r in d.get("relations", []))
    hosts = sorted(set(urllib.parse.urlparse(r.get("url", {}).get("resource", "")).netloc for r in d.get("relations", []) if r.get("type") == "review"))
    return {"rel_types": dict(types), "review_hosts": hosts, "rating_votes": (d.get("rating") or {}).get("votes-count", 0)}


def terms_check():
    print("\n=== robots/terms (only these pages are fetched) ===")
    for url in ["https://pitchfork.com/robots.txt", "https://www.metacritic.com/robots.txt",
                "https://www.albumoftheyear.org/robots.txt",
                "https://www.condenast.com/user-agreement", "https://www.albumoftheyear.org/terms/"]:
        try:
            body = request(url, timeout=20, retries=0)
        except Exception as e:
            print(url, "->", str(e)[:80])
            continue
        if url.endswith("robots.txt"):
            lines = [l for l in body.splitlines() if re.match(r"(user-agent|disallow|allow)\s*:", l, re.I)]
            print(url, f"({len(lines)} rules)")
            ua = None
            for l in lines[:400]:
                if l.lower().startswith("user-agent"):
                    ua = l.split(":", 1)[1].strip()
                if ua in ("*",) or "review" in l.lower() or "album" in l.lower():
                    print("   ", ua, "|", l.strip()[:120])
        else:
            txt = re.sub(r"<[^>]+>", " ", body)
            hits = [m.group(0) for m in re.finditer(r"[^.]{0,200}(scrap|spider|robot|crawl|automated)[^.]{0,200}\.", txt, re.I)]
            print(url, f"{len(hits)} relevant sentences")
            for h in hits[:4]:
                print("   >", re.sub(r"\s+", " ", h)[:400])


def main():
    arch = json.load(open("data/archive.json"))
    recent = json.load(open("data/reviews.json"))
    rng = random.Random(42)
    by_year = collections.defaultdict(list)
    for r in arch:
        if not r.get("guest") and r.get("artist_name") and r.get("album"):
            by_year[r["published"][:4]].append(r)
    sample = []
    for y in sorted(by_year):
        sample += [dict(x, bucket=y) for x in rng.sample(by_year[y], min(12, len(by_year[y])))]
    ids = {x["id"] for x in sample}
    sample += [dict(x, bucket="recent") for x in recent if x["id"] not in ids and not x.get("guest")]
    print(f"sample: {len(sample)} albums")
    now = datetime.now(timezone.utc)
    rows = []
    for i, r in enumerate(sample):
        row = {"bucket": r["bucket"], "artist": r["artist_name"], "album": r["album"], "score": r.get("score"),
               "days": (now - datetime.fromisoformat(r["published"])).days}
        try:
            title, text, qid = wiki_find(r["artist_name"], r["album"])
        except Exception as e:
            title, text, qid = None, None, None
            row["wp_error"] = str(e)[:80]
        row["wp"] = title
        row["qid"] = qid
        if text:
            row.update(analyse_wikitext(text))
        if r["bucket"] in ("recent", "2025", "2016", "2012") or i % 3 == 0:
            try:
                row["mb"] = mb_lookup(r["artist_name"], r["album"], r.get("mb_release_group"))
            except Exception as e:
                row["mb"] = {"error": str(e)[:60]}
        rows.append(row)
        time.sleep(0.4)
    wd = wikidata([x["qid"] for x in rows])
    for x in rows:
        if x.get("qid"):
            x["wd"] = wd.get(x["qid"])
    lab = labels({q for v in wd.values() for q in v["by"]})

    def pct(a, b):
        return f"{a}/{b} ({100 * a // max(b, 1)}%)"

    print("\n=== per bucket ===")
    print("bucket n | wp article | ratings box | >=5 outlets | MC | AOTY agg | charts | certs | RIAA | salesamount | wd P444")
    groups = collections.defaultdict(list)
    for x in rows:
        groups[x["bucket"]].append(x)
    era = {"2010-14": [x for x in rows if x["bucket"] in "2010 2011 2012 2013 2014".split()],
           "2015-19": [x for x in rows if x["bucket"] in "2015 2016 2017 2018 2019".split()],
           "2020-24": [x for x in rows if x["bucket"] in "2020 2021 2022 2023 2024".split()],
           "2025-26": [x for x in rows if x["bucket"] in ("2025", "2026")]}
    for name, g in list(sorted(groups.items())) + [("ERA " + k, v) for k, v in era.items()] + [("ALL", rows)]:
        n = len(g)
        f = lambda c: sum(1 for x in g if c(x))
        print(name, n, "|", pct(f(lambda x: x["wp"]), n), "|", pct(f(lambda x: x.get("has_ratings_box")), n), "|",
              pct(f(lambda x: len(x.get("outlets", {})) >= 5), n), "|",
              pct(f(lambda x: any(k in ("mc", "metacritic") for k in x.get("aggregates", {}))), n), "|",
              pct(f(lambda x: "aoty" in x.get("aggregates", {})), n), "|",
              pct(f(lambda x: x.get("chart_rows")), n), "|", pct(f(lambda x: x.get("cert_rows")), n), "|",
              pct(f(lambda x: any("united states" in c or c == "us" for c in x.get("cert_regions", []))), n), "|",
              pct(f(lambda x: x.get("sales_amount")), n), "|", pct(f(lambda x: (x.get("wd") or {}).get("p444")), n))

    print("\n=== outlet frequency in ratings boxes (share of albums with a box) ===")
    for name, g in [("ALL", rows)] + [("ERA " + k, v) for k, v in era.items()] + [("recent", groups["recent"])]:
        boxes = [x for x in g if x.get("has_ratings_box")]
        cnt = collections.Counter()
        for x in boxes:
            for o in {re.sub(r"\s+", " ", o).strip().lower() for o in x["outlets"]}:
                cnt[o] += 1
        print(f"-- {name}: {len(boxes)} boxes")
        print("   ", "; ".join(f"{o} {c}" for o, c in cnt.most_common(25)))
    aggk = collections.Counter(k for x in rows for k in x.get("aggregates", {}))
    print("aggregate keys:", dict(aggk))
    print("score formats sample:", [s for x in rows for s in list(x.get("outlets", {}).values())[:2]][:40])
    print("aggregate samples:", [x["aggregates"] for x in rows if x.get("aggregates")][:12])

    print("\n=== wikidata review scores (P444 by P447) ===")
    wcnt = collections.Counter(lab.get(q, q) for v in wd.values() for q in set(v["by"]))
    print("albums with qid:", sum(1 for x in rows if x.get("qid")), "with P444:", sum(1 for v in wd.values() if v["p444"]),
          "metacritic id:", sum(1 for v in wd.values() if v["metacritic_id"]))
    print("   ", "; ".join(f"{o} {c}" for o, c in wcnt.most_common(20)))

    print("\n=== musicbrainz ===")
    mbs = [x["mb"] for x in rows if isinstance(x.get("mb"), dict) and "rel_types" in x["mb"]]
    tried = sum(1 for x in rows if "mb" in x)
    print("tried", tried, "found", len(mbs), "with review rel", sum(1 for m in mbs if m["rel_types"].get("review")),
          "with wikidata rel", sum(1 for m in mbs if m["rel_types"].get("wikidata")),
          "rating votes>=3", sum(1 for m in mbs if m["rating_votes"] >= 3))
    print("   review hosts:", collections.Counter(h for m in mbs for h in m["review_hosts"]).most_common(10))

    print("\n=== charts / certs ===")
    ch = collections.Counter(c for x in rows for c in x.get("charts", []))
    print("charts:", ch.most_common(15))
    print("cert awards sample:", [a for x in rows for a in x.get("cert_awards", [])][:30])

    print("\n=== recent: days since review vs coverage ===")
    for x in sorted(groups["recent"] + groups.get("2026", []), key=lambda x: x["days"]):
        print(f"{x['days']:>4}d | {x['artist'][:22]:22} — {x['album'][:26]:26} | wp={'Y' if x['wp'] else '-'} box={len(x.get('outlets', {}))} agg={x.get('aggregates', {})} charts={x.get('chart_rows', 0)} certs={x.get('cert_rows', 0)}")

    print("\n=== album rows (all) ===")
    for x in rows:
        if x["bucket"] == "recent":
            continue
        print(f"{x['bucket']} | {x['artist'][:20]:20} — {x['album'][:24]:24} | sc={x['score']} | wp={'Y' if x['wp'] else '-'} box={len(x.get('outlets', {}))} agg={','.join(x.get('aggregates', {}))} ch={x.get('chart_rows', 0)} ce={x.get('cert_rows', 0)} wd={(x.get('wd') or {}).get('p444', '-')}")
    terms_check()


if __name__ == "__main__":
    main()
