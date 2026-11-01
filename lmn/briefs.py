"""Briefs for archive reviews: the same "brief", "about" (the site's longer one) and "who" lines the bot's cards have,
written by a free model (lmn/llm.py: Mistral, then Groq, then Cerebras) from the text of the review on theneedledrop.com. Newest first, at most BRIEFS_LIMIT per run
and BRIEFS_MINUTES of work; the rest next run.

Writes data/briefs.json: {review id: {"brief", "about", "who", "moods", "m": model}}. Skipped: guest reviews (not Fantano's
opinion), single-song reviews, reviews whose card already has a Gemini brief; posts without a text are kept as
{"skip": ...}, reviews no model answered for as {"fail": n} (left alone after FAIL_MAX runs).

Run: python -m lmn.briefs (workflow «Брифы для архива»). BRIEFS_COMPARE=1 writes nothing and instead puts three ways
of writing side by side on the 10 newest reviews without a brief (see compare)."""
import json
import os
import sys
import time
from pathlib import Path

from . import llm, tnd

DATA = Path(os.environ.get("DATA_DIR", "data"))
BATCH = 15
MIN_TEXT = 500
FAIL_MAX = 2  # runs in which no model gave a brief for this review: then it is left alone
GIVE_UP = 5  # failures in a row: the key, the plan or the service is wrong, no use going on


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


def finished(v):
    return bool(v.get("brief") or v.get("skip") or v.get("fail", 0) >= FAIL_MAX)


def entry(out):
    e = {"brief": (out.get("brief") or "").strip(), "about": (out.get("about") or "").strip(), "who": (out.get("who") or "").strip(), "moods": out.get("moods") or [],
         "m": out.get("model")}
    return {k: v for k, v in e.items() if v}


def save(path, data):
    path.write_text("{\n" + ",\n".join(json.dumps(k) + ": " + json.dumps(data[k], ensure_ascii=False, separators=(",", ":"))
                                        for k in sorted(data)) + "\n}\n")


def compare(archive, reviews):
    """The 10 newest reviews without a brief, written three ways, to choose how to write the archive's briefs: Groq in
    Russian; Groq in English, translated by Gemini in one request; Gemini itself from the text (one request each).
    Writes nothing; each row is printed as a "COMPARE {json}" log line and as a table in the run's summary."""
    from . import gemini
    picked = [(a, t) for a, t in texts(targets(archive, reviews, set())[:12]) if t and len(t) >= MIN_TEXT][:10]
    rows = []
    for a, text in picked:
        title = f"{a['artist_name']} - {a['album']}"
        rows.append({"id": a["id"], "title": title, "score": a.get("score"),
                     "groq_ru": llm.ask("groq", title, text) or {},
                     "groq_en": llm.ask("groq", title, text, lang="en") or {},
                     "gemini": gemini.summarize(title, text=text) or {}})
    tr = gemini.translate([r["groq_en"] for r in rows]) or [{} for _ in rows]
    for r, t in zip(rows, tr):
        r["groq_en_ru"] = t
        print("COMPARE " + json.dumps(r, ensure_ascii=False))

    def cell(x):
        return (f"{x.get('brief') or '—'}<br><br>{x.get('about') or '—'}<br><br>*{x.get('who') or ''}*").replace("|", "/")
    md = ("| Обзор | Groq по-русски | Groq по-английски → Gemini | Gemini сам |\n|---|---|---|---|\n"
          + "\n".join(f"| {r['title']} ({r['score']}) | {cell(r['groq_ru'])} | {cell(r['groq_en_ru'])} | {cell(r['gemini'])} |" for r in rows) + "\n")
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
    todo = targets(archive, reviews, {k for k, v in data.items() if finished(v)})
    print(f"briefs: {sum(1 for v in data.values() if v.get('brief'))} done, {len(todo)} to do, this run up to {limit}")
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
        out = llm.summarize(f"{a['artist_name']} - {a['album']}", text)
        if out and (out.get("brief") or "").strip():
            data[a["id"]] = entry(out)
            made += 1
            streak = []
            if made % 25 == 0:
                save(path, data)  # a timeout later in the run keeps what is done
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
    save(path, data)
    print(f"briefs: made {made}, failed {failed}, total {sum(1 for v in data.values() if v.get('brief'))}")


if __name__ == "__main__":
    run()
