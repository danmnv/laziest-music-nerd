"""Chat-completion APIs for archive briefs: Selectel's AI router (SELECTEL_API_KEY and SELECTEL_MODEL, paid, in roubles;
skipped until both are set), Mistral (MISTRAL_API_KEY; paid only, so skipped while there is no key), then Groq
(GROQ_API_KEY, free) when the one before fails;
a provider without a key is skipped. Same prompt and JSON answer as lmn/gemini.py, from the text of the review on
theneedledrop.com; Gemini's daily quota stays with new reviews. Returns None on any failure."""
import json
import os
import time

from . import gemini, http

# (name, url, key variable, default model, gap between requests in seconds, max characters of review text)
PROVIDERS = [
    # Selectel's AI router (docs.selectel.ru/ai-router): OpenAI-compatible, many models' providers behind one key, paid
    # per token in roubles. No default model: SELECTEL_MODEL is set once the owner picks one after a comparison.
    ("selectel", "https://api.selectel.ru/aig/v1/chat/completions", "SELECTEL_API_KEY",
     os.environ.get("SELECTEL_MODEL") or "", 0.5, 30000),
    ("mistral", "https://api.mistral.ai/v1/chat/completions", "MISTRAL_API_KEY",
     os.environ.get("MISTRAL_MODEL") or "mistral-medium-latest", 1.2, 30000),   # free plan: ~1 request per second
    # Groq's free plan: 30 requests a minute, tokens per minute
    # limited too, so a shorter text and a pause between reviews
    ("groq", "https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY",
     os.environ.get("GROQ_MODEL") or "llama-3.3-70b-versatile", 10, 14000),
]
# when the default model is gone (Groq retires models: llama-3.3-70b-versatile answered 404 model_not_found on
# 2026-11-01), the first of these the key can use, from the provider's /models list
PREFER = ["openai/gpt-oss-120b", "moonshotai/kimi-k2-instruct", "qwen/qwen3-32b", "meta-llama/llama-4-maverick-17b-128e-instruct",
          "gpt-oss-120b", "qwen-3-32b", "llama-3.3-70b"]
# Groq's free limits are per model (200k tokens a day each, console.groq.com/docs/rate-limits), so when the first model's
# day is used up, these write the rest (the owner chose qwen after a comparison on 2026-11-02; gpt-oss-20b broke its JSON).
EXTRA = {"groq": [m for m in (os.environ.get("GROQ_EXTRA_MODELS") or "qwen/qwen3.8-27b").split(",") if m.strip()]}
# what a provider's request carries besides the prompt: the router's "reasoning" field (as in its docs' example) keeps a
# thinking model's hidden tokens, billed as output, low
EXTRA_BODY = {"selectel": {"reasoning": {"effort": "low"}}}
_picked = {}
_last = {}
_dead = set()  # providers whose key is wrong (401/403) or still limited after retries (429) in this run
_spent = set()  # (provider, model) whose quota is gone for this run while the provider has other models


def models(name):
    """The provider's models in the order they are asked: the default (or the one picked instead), then EXTRA."""
    default = next(p[3] for p in PROVIDERS if p[0] == name)
    first = _picked.get(name) or default
    return [m for m in [first, *EXTRA.get(name, [])] if m and (name, m) not in _spent]


def ask(provider, title, text, model=None, sleep=time.sleep, clock=time.monotonic, lang="ru", verdict=""):
    name, url, var, default, gap, max_text = next(p for p in PROVIDERS if p[0] == provider)
    key = (os.environ.get(var) or "").strip()
    if not key or not text:
        return None
    model = model or _picked.get(name) or default
    if not model:
        return None
    moods = json.dumps(gemini.AI_MOODS, ensure_ascii=False)
    prompt = (gemini.PROMPT_EN.format(moods=moods, title=title, text=text[:max_text], verdict=verdict) if lang == "en" else
              gemini.PROMPT_RU.format(moods=moods, title=title, text=text[:max_text], verdict=verdict,
                                      en=gemini.EN_FIELD if lang == "both" else ""))
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}, "temperature": 0.4, **EXTRA_BODY.get(name, {})}
    for attempt in range(3):
        wait = _last.get(name, -1e9) + gap - clock()
        if wait > 0:
            sleep(wait)
        _last[name] = clock()
        try:
            raw = http.get_json(url, json_body=body, method="POST", headers={"Authorization": f"Bearer {key}"},
                                timeout=90, retries=0)
        except http.HttpError as e:
            print(f"{name} {model}: HTTP {e.status} {(e.body or '')[:200]}")
            if e.status in (401, 403):
                _dead.add(name)
                return None
            if e.status == 404 and "model" in (e.body or "") and model in EXTRA.get(name, []):
                _spent.add((name, model))  # an extra model renamed or retired: only it is dropped, not the provider
                return None
            if e.status == 404 and "model" in (e.body or "") and name not in _picked:
                _picked[name] = pick_model(url, key) or model
                if _picked[name] != model:
                    print(f"{name}: using {_picked[name]} instead")
                    model = body["model"] = _picked[name]
                    continue
                _dead.add(name)
                return None
            if e.status == 404 and "model" in (e.body or ""):  # the picked model is gone too: no use asking this provider
                _dead.add(name)
                return None
            if e.status == 0 and name == "selectel":  # no answer in 90 s (Kimi K2.6 thinks longer, 2026-11-03): paid
                return None                           # per token, a retry would only wait again; the next review goes on
            daily = e.status == 429 and "per day" in (e.body or "")  # the day's quota: waiting a minute won't help
            if e.status in (0, 429, 500, 502, 503, 504) and attempt < 2 and not daily:
                sleep(15 * (attempt + 1))  # rate limit or a hiccup: a bit later
                continue
            # The day's quota, or still limited after two waits: this provider's next model, or the next provider, for
            # the rest of the run. Dropping a model after a long busy minute too is deliberate: Mistral's key answers 429
            # to every request (free org plan), and retrying it for each review would cost 45 s a review.
            if e.status == 429:
                _spent.add((name, model))
                if not models(name):
                    _dead.add(name)
            return None
        try:
            out = gemini.parse_answer(raw["choices"][0]["message"]["content"])
            out["model"] = model
            out["usage"] = raw.get("usage") or {}  # tokens, for the cost of a paid model
            return out
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
            print(f"{name} {model}: bad response {e!r}")
            return None
    return None


def pick_model(chat_url, key):
    """A chat model this key can use, from the provider's OpenAI-style /models list, or None."""
    try:
        d = http.get_json(chat_url.replace("/chat/completions", "/models"), headers={"Authorization": f"Bearer {key}"}, retries=0)
    except http.HttpError as e:
        print(f"models list: HTTP {e.status}")
        return None
    ids = [m.get("id") for m in d.get("data", []) if m.get("id")]
    for p in PREFER:
        if p in ids:
            return p
    chat = [i for i in ids if not any(w in i for w in ("whisper", "guard", "tts", "embed", "audio", "vision"))]
    return chat[0] if chat else None


def available():
    """Some provider has a key and has not been given up on in this run."""
    return any(p[0] not in _dead and models(p[0]) and (os.environ.get(p[2]) or "").strip() for p in PROVIDERS)


def summarize(title, text, **kw):
    """The first provider that answers; within a provider, its first model with quota left."""
    for p in PROVIDERS:
        if p[0] in _dead or not (os.environ.get(p[2]) or "").strip():
            continue
        while p[0] not in _dead and models(p[0]):
            m = models(p[0])[0]
            out = ask(p[0], title, text, model=m, **kw)
            if out and (out.get("brief") or "").strip():
                return out
            if models(p[0])[:1] == [m]:  # not a quota problem (a bad answer, an outage): the next provider
                break  # (a model swapped for a retired one in ask() is spent under its new name, so the list moved on)
    return None
