"""Briefs for archive reviews: the same "brief", "about" (the site's longer one) and "who" lines the bot's cards have,
written by a model (lmn/llm.py; since 2026-11-04 GPT-6 Luna on Selectel's router, BRIEFS_LANG=both; before that
free Groq models in English and Gemini's translation) from the text of the review on theneedledrop.com. Newest first, at most BRIEFS_LIMIT per run,
BRIEFS_MINUTES of work and BRIEFS_MAX_RUB roubles spent (default 150); the rest next run.

BRIEFS_LANG=en (the default): the model writes in English and Gemini translates TR_BATCH of them per request (at most
BRIEFS_TRANSLATE_MAX requests a run, so new reviews keep Gemini's daily quota). The free models' own Russian was full of
calques (tried 2026-11-01 on Groq's openai/gpt-oss-120b: «светло‑приемлемую семёрку»), so in this mode briefs written in
Russian by them (no "tr") are written again. BRIEFS_LANG=ru: the model writes in Russian itself.
BRIEFS_LANG=both: the model writes the Russian texts and their English ("en") in one answer (a paid model on
Selectel's router, 2026-11-03), so no Gemini translation.

Writes data/briefs.json: {review id: {"brief", "about", "who", "moods", "m": model, "tr": translating model, "en": the
English}}; an entry with "en" and no "tr" waits for its translation. Skipped: guest reviews (not Fantano's
opinion), single-song reviews, reviews whose card already has a Gemini brief; posts without a text are kept as
{"skip": ...}, reviews no model answered for as {"fail": n} (left alone after FAIL_MAX runs).

Run: python -m lmn.briefs (workflow «Брифы для архива»). BRIEFS_COMPARE=1 writes nothing and instead puts other Groq
models next to the current one on two reviews (see compare)."""
import json
import os
import re
import sys
import time
from pathlib import Path

from . import gemini, http, llm, tnd

DATA = Path(os.environ.get("DATA_DIR", "data"))
BATCH = 15
MIN_TEXT = 500
FAIL_MAX = 2  # runs in which no model gave a brief for this review: then it is left alone
GIVE_UP = 5  # failures in a row: the key, the plan or the service is wrong, no use going on
TR_BATCH = 10  # briefs per Gemini translation request


def targets(archive, reviews, done):
    have = {r["id"] for r in reviews if (r.get("ai") or {}).get("brief")}
    out = [tnd.tidy_entry(a) for a in archive]
    out = [a for a in out if a.get("artist_name") and a.get("album") and not a.get("guest") and not a.get("track")
           and a["id"] not in done and a["id"] not in have and len(a["id"]) == 24]  # 24 hex: a TND post id
    return sorted(out, key=lambda a: a["published"], reverse=True)


def texts(items):
    for i in range(0, len(items), BATCH):
        chunk = items[i:i + BATCH]
        try:
            got = tnd.fetch_texts([a["id"] for a in chunk])
        except Exception as e:
            print(f"  ! TND texts: {e}", file=sys.stderr)
            got = None  # unknown, not "no text": these are tried again next run
        for a in chunk:
            yield a, (None if got is None else got.get(a["id"]) or "")


PROMPT_V = 3  # 2: no score in the text (2026-11-01); 3: GPT-6 Luna on Selectel writes Russian and English itself, brief
# about the release as a whole (the owner, 2026-11-04); entries written by an older prompt are written again


def finished(v, lang="ru"):
    if v.get("rf", 0) >= FAIL_MAX and v.get("rf_p") == PROMPT_V:
        return True  # an old brief the model failed to write again in FAIL_MAX runs: it stays (until a new prompt)
    if lang in ("en", "both") and v.get("brief") and not v.get("tr") and not v.get("en"):
        return False  # written in Russian by a model that writes it poorly: again, in English and translated
    if lang in ("en", "both") and (v.get("brief") or v.get("en")) and v.get("p", 1) < PROMPT_V:
        return False  # until then the site shows the old text with the score cut (gemini.drop_score)
    return bool(v.get("brief") or v.get("en") or v.get("skip") or v.get("fail", 0) >= FAIL_MAX)


NO_SCORE = "The card shows it above your text: never write it."


def tags(a):
    """The review's tags on theneedledrop.com (archive "genres"): genres and places, but labels, columns and names too,
    which the prompt says to leave out. For "who" when the text says little of the artist (owner, 2026-11-04: Kid Rock's
    came back empty)."""
    return [g.strip() for g in a.get("genres") or [] if isinstance(g, str) and g.strip()][:12]


def verdict(a):
    """The score as the review gives it, for the English prompt: for the model's sense of how much he liked it, not to
    write (owner, 2026-11-01: a repeat of the card's score line). Without it the models made one up (Kid Rock's
    "NOT GOOD" came back as 0/10, 1/10 and 2/10)."""
    if a.get("score") is not None:
        return f"Fantano's score: {a['score']}/10. {NO_SCORE}"
    if a.get("not_good"):
        return f'Fantano gave no number, his verdict is "NOT GOOD". {NO_SCORE}'
    if a.get("classic"):
        return f'Fantano gave no number, his verdict is "CLASSIC". {NO_SCORE}'
    return "Fantano gave no score: don't write one."


def entry(out, lang="ru"):
    """lang "both": the model wrote the Russian texts and their English ("en") in one answer, so it is its own
    translator ("tr")."""
    text = {k: (out.get(k) or "").strip() for k in ("brief", "about", "who")}
    if lang == "both":
        text = {**text, "en": out.get("en") or {}, "tr": out.get("model")}
    e = {**(text if lang != "en" else {"en": {k: v for k, v in text.items() if v}}), "moods": out.get("moods") or [], "m": out.get("model"),
         "p": PROMPT_V}
    return {k: v for k, v in e.items() if v}


TR_FAIL_MAX = 2  # runs in which Gemini gave no translation for this entry: then it is left alone


def untranslated(data):
    return [k for k, v in data.items() if v.get("en") and not v.get("tr") and v.get("trf", 0) < TR_FAIL_MAX]


def translate(data, budget, final=False):
    """Translates the English entries, TR_BATCH per Gemini request (the rest, fewer, only when final). Returns the
    requests left; 0 after a failed one, so the rest wait for the next run."""
    keys = untranslated(data)
    while budget > 0 and (len(keys) >= TR_BATCH or (final and keys)):
        chunk, keys = keys[:TR_BATCH], keys[TR_BATCH:]
        budget -= 1
        out = gemini.translate([data[k]["en"] for k in chunk])
        if not out:
            print("::warning::Gemini did not translate, the English ones wait for the next run")
            return 0
        for k, t in zip(chunk, out):
            if t.get("brief"):
                old = {f: v for f, v in data[k].items() if f not in ("brief", "about", "who", "trf")}  # an old Russian one goes now
                data[k] = {**old, **{f: t[f] for f in ("brief", "about", "who", "tr") if t.get(f)}}
            else:  # an empty one: not again and again, in every run's first batch
                data[k] = {**data[k], "trf": data[k].get("trf", 0) + 1}
    return budget


def save(path, data):
    path.write_text("{\n" + ",\n".join(json.dumps(k) + ": " + json.dumps(data[k], ensure_ascii=False, separators=(",", ":"))
                                        for k in sorted(data)) + "\n}\n")


COMPARE_MODELS = "qwen/qwen3.8-27b,openai/gpt-oss-20b"
CURRENT = "сейчас на сайте"


def compare(archive, reviews, data):
    """Other models next to the briefs already on the site, to choose one: writes nothing; rows go to the log
    ("COMPARE {json}") and as a table to the run's summary. Takes the BRIEFS_COMPARE_N (2) newest reviews already
    written and translated, and asks each of BRIEFS_COMPARE_MODELS:
    - a plain name is a Groq model (each has its own free daily quota, 2026-11-02): it writes in English and Gemini
      translates them all in one request, like the real run;
    - "selectel:<model>" goes to Selectel's router and writes the Russian and the English texts itself in one answer
      (gemini.PROMPT_RU with EN_FIELD), as a paid model would in the real run, with its tokens and seconds for the
      cost (2026-11-03);
    - "selectel:list" only lists the router's models (their ids for the names above); "selectel:list:<regex>" only
      those whose id matches."""
    n = int(os.environ.get("BRIEFS_COMPARE_N") or "2")
    models = [m.strip() for m in (os.environ.get("BRIEFS_COMPARE_MODELS") or COMPARE_MODELS).split(",") if m.strip()]
    if os.environ.get("BRIEFS_PING") == "1":
        return ping([m.split(":", 1)[1] for m in models if m.startswith("selectel:")])
    lst = next((m for m in models if m.startswith("selectel:list")), None)
    if lst:
        return list_models("selectel", lst[len("selectel:list:"):])
    by_id = {tnd.tidy_entry(a)["id"]: tnd.tidy_entry(a) for a in archive}
    done = sorted((k for k, v in data.items() if v.get("tr") and v.get("brief") and k in by_id),
                  key=lambda k: by_id[k]["published"], reverse=True)
    ids = [k.strip() for k in (os.environ.get("BRIEFS_COMPARE_IDS") or "").split(",") if k.strip() in by_id]
    picked = [(a, t) for a, t in texts([by_id[k] for k in (ids or done[:n + 2])]) if t and len(t) >= MIN_TEXT][:len(ids) or n]
    rows, en = [], []
    for a, text in picked:
        title = f"{a['artist_name']} - {a['album']}"
        row = {"id": a["id"], "title": title, CURRENT: {f: (data.get(a["id"]) or {}).get(f) for f in ("who", "brief", "about", "en", "m")}}
        for m in models:
            if sum(1 for r in rows if not r[m].get("model")) >= 2:  # no answer twice: a slow or broken model, not tried again
                row[m] = {}
                continue
            provider, model, lang = ("selectel", m.split(":", 1)[1], "both") if m.startswith("selectel:") else ("groq", m, "en")
            t0 = time.monotonic()
            out = llm.ask(provider, title, text, model=model, lang=lang, verdict=verdict(a), tags=tags(a)) or {}
            u = out.get("usage") or {}
            row[m] = {"model": out.get("model"), "sec": round(time.monotonic() - t0),  # the model that really answered
                      "in": u.get("prompt_tokens"), "out": u.get("completion_tokens"),
                      "cost": u.get("cost")}  # Selectel's own charge in roubles, surcharges included (2026-11-03)
            print(f"compare {title} / {m}: {row[m]['sec']} s, {'ok' if out.get('brief') else 'no answer'}", flush=True)
            got = {k: out[k] for k in ("brief", "about", "who", "en") if out.get(k)}
            if lang == "en":
                en.append((row, m, got))
            else:
                row[m].update(got)
        rows.append(row)
    if en:
        tr = gemini.translate([e for _, _, e in en]) or [{} for _ in en]
        for (row, m, e), t in zip(en, tr):
            row[m].update(t if e else {})
    for r in rows:
        print("COMPARE " + json.dumps(r, ensure_ascii=False))

    def cell(x):
        rub = f", {x['cost']:.2f} ₽" if isinstance(x.get("cost"), (int, float)) else ""
        cost = f"<br><br><sub>{x['sec']} с, {x['in']} → {x['out']} токенов{rub}</sub>" if x.get("in") else ""
        en = x.get("en") or {}
        en = f"<br><br><i>EN: {en.get('who') or '—'}<br><br>{en.get('brief') or '—'}<br><br>{en.get('about') or '—'}</i>" if en else ""
        return (f"{x.get('who') or '—'}<br><br>{x.get('brief') or '—'}<br><br>{x.get('about') or '—'}{en}{cost}").replace("|", "/")
    cols = [CURRENT] + models
    md = ("| Обзор | " + " | ".join(cols) + " |\n|---|" + "---|" * len(cols) + "\n"
          + "\n".join(f"| {r['title']} | " + " | ".join(cell(r[c]) for c in cols) + " |" for r in rows) + "\n")
    tot = [(m, sum(r[m].get("in") or 0 for r in rows), sum(r[m].get("out") or 0 for r in rows),
            sum(1 for r in rows if r[m].get("brief"))) for m in models]
    md += "\n| Модель | ответила | токенов на входе | на выходе |\n|---|---|---|---|\n" + "".join(
        f"| {m} | {ok} из {len(rows)} | {i} | {o} |\n" for m, i, o, ok in tot)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(md)
    return rows


def ping(models):
    """A one-word request to each Selectel model, with and without the "reasoning" field: tells a model that does not
    answer at all from one that only needs longer than the timeout for a brief (Kimi K2.6 and GLM 5.3, 2026-11-03)."""
    url, var = next((p[1], p[2]) for p in llm.PROVIDERS if p[0] == "selectel")
    key = (os.environ.get(var) or "").strip()
    for m in models:
        for extra in ({"reasoning": {"effort": "low"}}, {}):
            t0 = time.monotonic()
            body = {"model": m, "messages": [{"role": "user", "content": "Ответь одним словом: привет."}], **extra}
            try:
                d = http.get_json(url, json_body=body, method="POST", headers={"Authorization": f"Bearer {key}"},
                                  timeout=float(os.environ.get("SELECTEL_TIMEOUT") or 90), retries=0)
                got = f"ok {d['choices'][0]['message'].get('content')!r:.40} usage={d.get('usage')}"
            except http.HttpError as e:
                got = f"HTTP {e.status} {(e.body or '')[:200]}"
            except (KeyError, IndexError, TypeError) as e:
                got = f"bad answer {e!r}"
            print(f"ping {m} {'reasoning low' if extra else 'no reasoning field'}: {round(time.monotonic() - t0)} s, {got}", flush=True)


def list_models(provider, match=""):
    """The provider's /models list (ids and whatever price fields it gives) to the log and the run's summary."""
    url, var = next((p[1], p[2]) for p in llm.PROVIDERS if p[0] == provider)
    try:
        d = http.get_json(url.replace("/chat/completions", "/models"),
                          headers={"Authorization": f"Bearer {(os.environ.get(var) or '').strip()}"}, retries=1)
    except http.HttpError as e:
        print(f"::warning::{provider} models list: HTTP {e.status} {(e.body or '')[:300]}")
        return []
    items = sorted((m for m in d.get("data") or [] if re.search(match, str(m.get("id")), re.I)), key=lambda m: str(m.get("id")))
    def price(m):  # roubles per token (seen 2026-11-03) -> per million
        pr = m.get("pricing") or {}
        return " ".join(f"{k}={float(v) * 1e6:g}" for k, v in pr.items() if k in ("prompt", "completion", "internal_reasoning"))
    lines = [f"{m.get('id')}  ₽/1M: {price(m)}" for m in items]
    print(f"{provider}: {len(items)} models\n" + "\n".join(lines))
    if items:
        print("first entry as given: " + json.dumps(items[0], ensure_ascii=False)[:1500])
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("```\n" + "\n".join(lines) + "\n```\n")
    return items


def run():
    archive = json.loads((DATA / "archive.json").read_text())
    rpath = DATA / "reviews.json"
    reviews = json.loads(rpath.read_text()) if rpath.exists() else []
    path = DATA / "briefs.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    if os.environ.get("BRIEFS_COMPARE") == "1":
        return compare(archive, reviews, data)
    lang = os.environ.get("BRIEFS_LANG") or "en"
    # en: 150 = what 15 Gemini translation requests of 10 take; both: no translation, BRIEFS_MINUTES is the limit
    limit = int(os.environ.get("BRIEFS_LIMIT") or ("150" if lang == "en" else "2000"))
    budget = int(os.environ.get("BRIEFS_TRANSLATE_MAX") or "15")
    max_rub = float(os.environ.get("BRIEFS_MAX_RUB") or "150")
    todo = targets(archive, reviews, {k for k, v in data.items() if finished(v, lang)})
    print(f"briefs ({lang}): {sum(1 for v in data.values() if v.get('brief'))} done, {len(untranslated(data))} to translate, "
          f"{len(todo)} to write, this run up to {limit}")
    made = failed = tried = 0
    streak = []  # (id, previous entry) of the failures in a row
    deadline = time.monotonic() + 60 * float(os.environ.get("BRIEFS_MINUTES", "100"))
    for a, text in texts(todo):  # the whole list, lazily: skipped ones don't use up the limit
        if tried >= limit:
            break
        if time.monotonic() > deadline:  # stop and save before the job's time runs out; the rest next run
            print("briefs: time is up for this run")
            break
        if text is None:
            continue
        if llm.stats["rub"] >= max_rub:  # the run's spending cap: the key itself has no limit
            print(f"::warning::spent {llm.stats['rub']:.2f} ₽, the cap for a run is {max_rub:g} ₽, stopping")
            break
        if not llm.available(lang):  # no key, or every provider gave up: the setup's fault, not this review's
            print("::warning::no model available (keys missing, wrong or out of quota), stopping")
            break
        if len(text) < MIN_TEXT:
            data[a["id"]] = {"skip": "no text" if not text else "short"}  # remembered, so it isn't fetched every run
            continue
        tried += 1
        title = f"{a['artist_name']} - {a['album']}"
        out = llm.summarize(title, text, lang=lang, verdict=verdict(a), tags=tags(a))
        if out and (out.get("brief") or "").strip():
            old = data.get(a["id"]) or {}
            data[a["id"]] = entry(out, lang)
            if lang == "en" and old.get("brief"):  # the old Russian one stays on the site until the translation comes
                data[a["id"]].update({f: old[f] for f in ("brief", "about", "who") if old.get(f)})
            made += 1
            streak = []
            if lang == "en":
                budget = translate(data, budget)
            if made % 25 == 0:
                save(path, data)  # a timeout later in the run keeps what is done
        else:
            streak.append((a["id"], data.get(a["id"])))
            failed += 1
            prev = data.get(a["id"]) or {}
            if prev.get("brief"):  # an old brief to write again is kept until a new one comes; tried FAIL_MAX runs
                rf = prev.get("rf", 0) if prev.get("rf_p") == PROMPT_V else 0  # counted again for a new prompt
                data[a["id"]] = {**prev, "rf": rf + 1, "rf_p": PROMPT_V}  # (a new dict: an outage restores the old one)
            else:
                data[a["id"]] = {"fail": prev.get("fail", 0) + 1}  # given up after FAIL_MAX runs
            if len(streak) >= GIVE_UP:  # likely an outage, not these reviews: their failures are not counted
                for k, prev in streak:
                    if prev is None:
                        data.pop(k, None)
                    else:
                        data[k] = prev
                print(f"::warning::no model answered {GIVE_UP} times in a row, stopping")
                break
    if lang == "en":
        translate(data, budget, final=True)
    save(path, data)
    print(f"briefs: made {made}, failed {failed}, total {sum(1 for v in data.values() if v.get('brief'))}, "
          f"waiting for translation {len(untranslated(data))}")
    if llm.stats["rub"] or llm.stats["timeouts"]:
        print(f"briefs: spent {llm.stats['rub']:.2f} ₽, {llm.stats['timeouts']} requests timed out")


if __name__ == "__main__":
    run()
