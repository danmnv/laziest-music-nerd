"""DeepL API Free (DEEPL_API_KEY, 500,000 characters a month): English briefs -> Russian. One request for a batch.
Returns None on any failure, so the caller can fall back to Gemini (lmn/gemini.py translate)."""
import os

from . import gemini, http

FIELDS = ("brief", "about", "who")


def translate(items, api_key=None):
    """English brief/about/who dicts -> the same list in Russian, or None."""
    key = (api_key or os.environ.get("DEEPL_API_KEY") or "").strip()
    if not key or not items:
        return None
    texts = [str(x.get(k) or "") for x in items for k in FIELDS]
    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"  # Free keys end in ":fx"
    try:
        d = http.get_json(f"https://{host}/v2/translate", method="POST", headers={"Authorization": f"DeepL-Auth-Key {key}"},
                          json_body={"text": texts, "source_lang": "EN", "target_lang": "RU", "formality": "prefer_less"},
                          timeout=60, retries=1)
        out = [t["text"] for t in d["translations"]]
    except (http.HttpError, KeyError, TypeError) as e:
        print(f"deepl: {getattr(e, 'status', '')} {e!r}"[:300])
        return None
    if len(out) != len(texts):
        return None
    res = []
    for i, x in enumerate(items):
        got = out[i * len(FIELDS):(i + 1) * len(FIELDS)]
        t = {k: (t.strip() if x.get(k) else "") for k, t in zip(FIELDS, got)}
        res.append(t | {"brief": gemini.trim_brief(t["brief"]), "about": gemini.trim_about(t["about"]), "tr": "deepl"})
    return res
