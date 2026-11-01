"""Free chat-completion APIs for archive briefs: Mistral (free "Experiment" plan, MISTRAL_API_KEY) first, then Groq
(GROQ_API_KEY) and Cerebras (CEREBRAS_API_KEY) when the one before fails;
a provider without a key is skipped. Same prompt and JSON answer as lmn/gemini.py, from the text of the review on
theneedledrop.com; Gemini's daily quota stays with new reviews. Returns None on any failure."""
import json
import os
import time

from . import gemini, http

# (name, url, key variable, default model, gap between requests in seconds, max characters of review text)
PROVIDERS = [
    ("mistral", "https://api.mistral.ai/v1/chat/completions", "MISTRAL_API_KEY",
     os.environ.get("MISTRAL_MODEL") or "mistral-medium-latest", 1.2, 30000),   # free plan: ~1 request per second
    # free plans of Groq (~1000 requests a day) and Cerebras (~1M tokens a day): 30 requests a minute, tokens per minute
    # limited too, so a shorter text and a pause between reviews
    ("groq", "https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY",
     os.environ.get("GROQ_MODEL") or "llama-3.3-70b-versatile", 10, 14000),
    ("cerebras", "https://api.cerebras.ai/v1/chat/completions", "CEREBRAS_API_KEY",
     os.environ.get("CEREBRAS_MODEL") or "llama-3.3-70b", 10, 14000),
]
# when the default model is gone (Groq retires models: llama-3.3-70b-versatile answered 404 model_not_found on
# 2026-11-01), the first of these the key can use, from the provider's /models list
PREFER = ["openai/gpt-oss-120b", "moonshotai/kimi-k2-instruct", "qwen/qwen3-32b", "meta-llama/llama-4-maverick-17b-128e-instruct",
          "gpt-oss-120b", "qwen-3-32b", "llama-3.3-70b"]
_picked = {}
_last = {}
_dead = set()  # providers whose key is wrong (401/403) or still limited after retries (429) in this run


def ask(provider, title, text, model=None, sleep=time.sleep, clock=time.monotonic, lang="ru", verdict=""):
    name, url, var, default, gap, max_text = next(p for p in PROVIDERS if p[0] == provider)
    key = (os.environ.get(var) or "").strip()
    if not key or not text:
        return None
    model = model or _picked.get(name) or default
    moods = json.dumps(gemini.AI_MOODS, ensure_ascii=False)
    prompt = (gemini.PROMPT_EN.format(moods=moods, title=title, text=text[:max_text], verdict=verdict) if lang == "en" else
              gemini.PROMPT.format(source=gemini.SOURCE_TEXT, moods=moods, title=title, text="\nТекст обзора:\n" + text[:max_text]))
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}, "temperature": 0.4}
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
            if e.status in (0, 429, 500, 502, 503, 504) and attempt < 2:
                sleep(15 * (attempt + 1))  # rate limit or a hiccup: a bit later
                continue
            if e.status == 429:  # still limited after two waits: quota gone for now, the next provider for the rest
                _dead.add(name)
            return None
        try:
            out = gemini.parse_answer(raw["choices"][0]["message"]["content"])
            out["model"] = model
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
    return any(p[0] not in _dead and (os.environ.get(p[2]) or "").strip() for p in PROVIDERS)


def summarize(title, text, **kw):
    """The first provider that answers."""
    for p in PROVIDERS:
        if p[0] in _dead or not (os.environ.get(p[2]) or "").strip():
            continue
        out = ask(p[0], title, text, **kw)
        if out and (out.get("brief") or "").strip():
            return out
    return None
