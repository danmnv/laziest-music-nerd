"""Check that every secret works. Prints OK/FAIL per service, never the values."""
import json
import os
import urllib.parse

from . import http


def check(name, fn):
    try:
        print(f"OK   {name}: {fn()}")
        return True
    except Exception as ex:
        msg = getattr(ex, "body", "") or str(ex)
        if getattr(ex, "status", None) == 429:
            from .gemini import _reason
            msg = _reason(msg)
        for k in ("TELEGRAM_BOT_TOKEN", "GEMINI_API_KEY", "YOUTUBE_API_KEY"):
            if os.environ.get(k):
                msg = msg.replace(os.environ[k], "***")
        print(f"FAIL {name}: {type(ex).__name__} {getattr(ex, 'status', '')} {msg[:300]}")
        return False


def telegram():
    tok = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    me = http.get_json(f"https://api.telegram.org/bot{tok}/getMe")["result"]
    return "@" + me["username"]


def channel():
    tok, raw = os.environ["TELEGRAM_BOT_TOKEN"].strip(), os.environ["TELEGRAM_CHANNEL"]
    ch = raw.strip()
    print(f"     channel value: {ch!r} (raw length {len(raw)})")
    bot_id = tok.split(":")[0]
    m = http.get_json(f"https://api.telegram.org/bot{tok}/getChatMember?chat_id={urllib.parse.quote(ch)}&user_id={bot_id}")["result"]
    if m["status"] != "administrator" or not m.get("can_post_messages"):
        raise RuntimeError(f"bot is {m['status']}, can_post_messages={m.get('can_post_messages')}")
    return f"{ch}: bot is admin, can post, can edit={m.get('can_edit_messages')}"


def private_chat():
    tok = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    from .check import worker_owner_id
    if worker_owner_id():
        return "the Worker knows the owner"
    try:
        ups = http.get_json(f"https://api.telegram.org/bot{tok}/getUpdates")["result"]
    except http.HttpError as ex:
        if ex.status == 409:  # a webhook is set (the Worker is deployed) but it didn't tell us the owner
            raise RuntimeError("webhook is set, so getUpdates is closed, and the Worker gave no owner id") from None
        raise
    n = len({u["message"]["chat"]["id"] for u in ups if u.get("message", {}).get("chat", {}).get("type") == "private"})
    if n != 1:
        raise RuntimeError(f"private chats seen: {n} (need exactly 1: press /start in the bot)")
    return "owner's /start found"


def gemini():
    """One real call down the model list. Off unless DOCTOR_GEMINI_CALL=1: every call spends the free daily limit."""
    if os.environ.get("DOCTOR_GEMINI_CALL") != "1":
        return "call skipped to save the daily limit (the key itself is checked by 'gemini models')"
    from . import gemini as g
    model, d = g.generate({"contents": [{"parts": [{"text": "Ответь одним словом: привет"}]}]},
                          os.environ["GEMINI_API_KEY"].strip(), budget=60)
    if d is None:
        raise RuntimeError("no model answered (see the lines above)")
    return f"{model} answered: {d['candidates'][0]['content']['parts'][0]['text'].strip()[:40]}"


def gemini_models():
    from .gemini import MODELS
    d = http.get_json("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                      headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"].strip()})
    names = {m["name"].split("/", 1)[1] for m in d.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])}
    missing = [m for m in MODELS if m not in names]
    if len(missing) == len(MODELS):
        raise RuntimeError(f"none of {MODELS} is offered to this key; flash models it has: {sorted(n for n in names if 'flash' in n)}")
    return f"key works; model list: {', '.join(MODELS)}" + (f" (not offered: {', '.join(missing)})" if missing else "")


def youtube():
    d = http.get_json("https://www.googleapis.com/youtube/v3/channels?part=statistics&forHandle=@theneedledrop&key=" + os.environ["YOUTUBE_API_KEY"].strip())
    return f"TND channel videos: {d['items'][0]['statistics']['videoCount']}"


if __name__ == "__main__":
    results = [check(n, f) for n, f in [("telegram bot", telegram), ("telegram channel", channel), ("owner /start", private_chat),
                                        ("gemini", gemini), ("gemini models", gemini_models), ("youtube", youtube)]]
    print(json.dumps({"ok": sum(results), "total": len(results)}))
