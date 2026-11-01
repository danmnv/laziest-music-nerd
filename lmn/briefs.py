"""Briefs for archive reviews: the same "brief", "about" (the site's longer one) and "who" lines the bot's cards have,
written by a free model (lmn/llm.py: Mistral, then Groq, then Cerebras) from the text of the review on theneedledrop.com. Newest first, at most BRIEFS_LIMIT per run
and BRIEFS_MINUTES of work; the rest next run.

BRIEFS_LANG=en (the default): the model writes in English and Gemini translates TR_BATCH of them per request (at most
BRIEFS_TRANSLATE_MAX requests a run, so new reviews keep Gemini's daily quota). The free models' own Russian was full of
calques (tried 2026-11-01 on Groq's openai/gpt-oss-120b: «светло‑приемлемую семёрку»), so in this mode briefs written in
Russian by them (no "tr") are written again. BRIEFS_LANG=ru: the model writes in Russian itself.

Writes data/briefs.json: {review id: {"brief", "about", "who", "moods", "m": model, "tr": translating model, "en": the
English}}; an entry with "en" and no "brief" waits for its translation. Skipped: guest reviews (not Fantano's
opinion), single-song reviews, reviews whose card already has a Gemini brief; posts without a text are kept as
{"skip": ...}, reviews no model answered for as {"fail": n} (left alone after FAIL_MAX runs).

Run: python -m lmn.briefs (workflow «Брифы для архива»). BRIEFS_COMPARE=1 writes nothing and instead puts three ways
of writing side by side on the 10 newest reviews without a brief (see compare)."""
import json
import os
import sys
import time
from pathlib import Path

from . import gemini, llm, tnd

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


def finished(v, lang="ru"):
    if lang == "en" and v.get("brief") and not v.get("tr") and not v.get("en"):
        return False  # written in Russian by a model that writes it poorly: again, in English and translated
    return bool(v.get("brief") or v.get("en") or v.get("skip") or v.get("fail", 0) >= FAIL_MAX)


def verdict(a):
    """The score as the review gives it, for the English prompt: the models made one up when there was none
    (Kid Rock's "NOT GOOD" came back as 0/10, 1/10 and 2/10)."""
    if a.get("score") is not None:
        return f"Fantano's score: {a['score']}/10."
    if a.get("not_good"):
        return 'Fantano gave no number, his verdict is "NOT GOOD": write that instead of a score.'
    if a.get("classic"):
        return 'Fantano gave no number, his verdict is "CLASSIC": write that instead of a score.'
    return "Fantano gave no score: don't write one."


def entry(out, lang="ru"):
    text = {k: (out.get(k) or "").strip() for k in ("brief", "about", "who")}
    e = {**(text if lang == "ru" else {"en": {k: v for k, v in text.items() if v}}), "moods": out.get("moods") or [], "m": out.get("model")}
    return {k: v for k, v in e.items() if v}


def untranslated(data):
    return [k for k, v in data.items() if v.get("en") and not v.get("brief")]


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
                data[k] = {**data[k], **{f: t[f] for f in ("brief", "about", "who", "tr") if t.get(f)}}
    return budget


def save(path, data):
    path.write_text("{\n" + ",\n".join(json.dumps(k) + ": " + json.dumps(data[k], ensure_ascii=False, separators=(",", ":"))
                                        for k in sorted(data)) + "\n}\n")


def compare(archive, reviews):
    """The 10 newest reviews without a brief, written three ways, to choose how to write the archive's briefs: Groq in
    Russian; Groq in English, translated by Gemini in one request; Gemini itself from the text (one request each).
    Writes nothing; each row is printed as a "COMPARE {json}" log line and as a table in the run's summary."""
    from . import deepl, gemini
    picked = [(a, t) for a, t in texts(targets(archive, reviews, set())[:12]) if t and len(t) >= MIN_TEXT][:10]
    rows = []
    for a, text in picked:
        title = f"{a['artist_name']} - {a['album']}"
        rows.append({"id": a["id"], "title": title, "score": a.get("score"),
                     "groq_ru": llm.ask("groq", title, text) or {},
                     "groq_en": llm.ask("groq", title, text, lang="en", verdict=verdict(a)) or {},
                     "gemini": gemini.summarize(title, text=text) or {}})
    tr = gemini.translate([r["groq_en"] for r in rows]) or [{} for _ in rows]
    dl = deepl.translate([r["groq_en"] for r in rows]) or [{} for _ in rows]  # only with DEEPL_API_KEY
    for r, t, d in zip(rows, tr, dl):
        r["groq_en_ru"], r["groq_en_deepl"] = t, d
        print("COMPARE " + json.dumps(r, ensure_ascii=False))

    def cell(x):
        return (f"{x.get('brief') or '—'}<br><br>{x.get('about') or '—'}<br><br>*{x.get('who') or ''}*").replace("|", "/")
    md = ("| Обзор | Groq по-русски | Groq по-английски → Gemini | Groq по-английски → DeepL | Gemini сам |\n|---|---|---|---|---|\n"
          + "\n".join(f"| {r['title']} ({r['score']}) | {cell(r['groq_ru'])} | {cell(r['groq_en_ru'])} | {cell(r['groq_en_deepl'])} | "
                      f"{cell(r['gemini'])} |" for r in rows) + "\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(md)


def run():
    archive = json.loads((DATA / "archive.json").read_text())
    rpath = DATA / "reviews.json"
    reviews = json.loads(rpath.read_text()) if rpath.exists() else []
    if os.environ.get("BRIEFS_COMPARE") == "1":
        return compare(archive, reviews)
    path = DATA / "briefs.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    limit = int(os.environ.get("BRIEFS_LIMIT", "300"))
    lang = os.environ.get("BRIEFS_LANG") or "en"
    budget = int(os.environ.get("BRIEFS_TRANSLATE_MAX") or "15")
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
        if not llm.available():  # no key, or every provider gave up: the setup's fault, not this review's
            print("::warning::no model available (keys missing, wrong or out of quota), stopping")
            break
        if len(text) < MIN_TEXT:
            data[a["id"]] = {"skip": "no text" if not text else "short"}  # remembered, so it isn't fetched every run
            continue
        tried += 1
        title = f"{a['artist_name']} - {a['album']}"
        out = llm.summarize(title, text, lang="en", verdict=verdict(a)) if lang == "en" else llm.summarize(title, text)
        if out and (out.get("brief") or "").strip():
            data[a["id"]] = entry(out, lang)
            made += 1
            streak = []
            if lang == "en":
                budget = translate(data, budget)
            if made % 25 == 0:
                save(path, data)  # a timeout later in the run keeps what is done
        elif (data.get(a["id"]) or {}).get("brief"):  # an old Russian brief to write again: kept until a new one comes
            failed += 1
        else:
            streak.append((a["id"], data.get(a["id"])))
            data[a["id"]] = {"fail": (data.get(a["id"]) or {}).get("fail", 0) + 1}  # given up after FAIL_MAX runs
            failed += 1
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


if __name__ == "__main__":
    run()
