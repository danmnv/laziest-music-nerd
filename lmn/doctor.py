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
        for k in ("TELEGRAM_BOT_TOKEN", "GEMINI_API_KEY", "YOUTUBE_API_KEY"):
            if os.environ.get(k):
                msg = msg.replace(os.environ[k], "***")
        print(f"FAIL {name}: {type(ex).__name__} {getattr(ex, 'status', '')} {msg[:300]}")
        return False


def telegram():
    tok = os.environ["TELEGRAM_BOT_TOKEN"]
    me = http.get_json(f"https://api.telegram.org/bot{tok}/getMe")["result"]
    return "@" + me["username"]


def channel():
    tok, ch = os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHANNEL"]
    bot_id = tok.split(":")[0]
    m = http.get_json(f"https://api.telegram.org/bot{tok}/getChatMember?chat_id={urllib.parse.quote(ch)}&user_id={bot_id}")["result"]
    if m["status"] != "administrator" or not m.get("can_post_messages"):
        raise RuntimeError(f"bot is {m['status']}, can_post_messages={m.get('can_post_messages')}")
    return f"{ch}: bot is admin, can post, can edit={m.get('can_edit_messages')}"


def private_chat():
    tok = os.environ["TELEGRAM_BOT_TOKEN"]
    ups = http.get_json(f"https://api.telegram.org/bot{tok}/getUpdates")["result"]
    n = len({u["message"]["chat"]["id"] for u in ups if u.get("message", {}).get("chat", {}).get("type") == "private"})
    if n != 1:
        raise RuntimeError(f"private chats seen: {n} (need exactly 1: press /start in the bot)")
    return "owner's /start found"


def gemini():
    from .gemini import MODEL
    body = {"contents": [{"parts": [{"text": "Ответь одним словом: привет"}]}]}
    d = http.get_json(f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent", method="POST",
                      json_body=body, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, retries=0)
    return f"{MODEL} answered: {d['candidates'][0]['content']['parts'][0]['text'].strip()[:40]}"


def youtube():
    d = http.get_json("https://www.googleapis.com/youtube/v3/channels?part=statistics&forHandle=@theneedledrop&key=" + os.environ["YOUTUBE_API_KEY"])
    return f"TND channel videos: {d['items'][0]['statistics']['videoCount']}"


if __name__ == "__main__":
    results = [check(n, f) for n, f in [("telegram bot", telegram), ("telegram channel", channel), ("owner /start", private_chat),
                                        ("gemini", gemini), ("youtube", youtube)]]
    print(json.dumps({"ok": sum(results), "total": len(results)}))
