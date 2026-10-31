"""Hourly job: find new TND album reviews, post a card to the channel, refresh the pinned 60-day list.

MODE=run   (default) normal hourly run
MODE=dry   no Telegram calls, print what would be sent
MODE=test  send the newest review's card to the owner's private chat only; nothing is saved
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import card, http, tnd
from .enrich import archive_entry, enrich
from .telegram import Telegram

DATA = Path(os.environ.get("DATA_DIR", "data"))
MODE = os.environ.get("MODE", "run")


def load(name, default):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else default


def save(name, obj):
    DATA.mkdir(exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


def send_card(tg, chat_id, r):
    text = card.caption(r)
    kb = card.buttons(r, with_callbacks=os.environ.get("WORKER_LIVE") == "1")
    for url in r.get("covers", []):
        try:
            return tg.send_photo_file(chat_id, http.get_bytes(url), text, kb)
        except Exception as ex:  # try the next cover
            print(f"cover failed ({type(ex).__name__}), trying next")
    return tg.send_message(chat_id, text, kb)


def owner_chat(tg):
    if os.environ.get("TELEGRAM_OWNER_ID"):
        return int(os.environ["TELEGRAM_OWNER_ID"])
    ups = tg.call("getUpdates", limit=100)
    chats = {u["message"]["chat"]["id"] for u in ups if u.get("message", {}).get("chat", {}).get("type") == "private"}
    if len(chats) != 1:
        sys.exit(f"test mode: expected exactly one private chat with the bot, found {len(chats)}. Set TELEGRAM_OWNER_ID.")
    return chats.pop()


def main():
    reviews = load("reviews.json", [])
    state = load("state.json", {})
    archive = load("archive.json", [])
    known = {r["id"] for r in reviews}

    if not archive:
        print("building archive index from TND…")
        archive = [archive_entry(tnd.parse_post(p)) for p in tnd.fetch_all_light()]
        print(f"archive: {len(archive)} reviews")
    arch_ids = {a["id"] for a in archive}

    seeding = not state.get("seeded")
    since = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    posts = tnd.fetch_posts(limit=50 if seeding else 15, with_text=True, since=since if seeding else None)["posts"]
    posts.sort(key=lambda p: p["published_at"])

    if MODE == "test":
        p = posts[-1]
        r = next((x for x in reviews if x["id"] == p["id"]), None) or enrich(tnd.parse_post(p), p.get("plaintext"), archive)
        tg = Telegram()
        send_card(tg, owner_chat(tg), r)
        print("test card sent to the owner's private chat:", r["title"])
        return

    tg = Telegram() if MODE == "run" else None
    channel = os.environ.get("TELEGRAM_CHANNEL")
    new = [p for p in posts if p["id"] not in known]
    if MODE == "dry" and os.environ.get("DRY_LIMIT"):
        new = new[-int(os.environ["DRY_LIMIT"]):]
    print(f"{len(new)} new review(s){' (seeding, no cards)' if seeding else ''}")
    for p in new:
        rev = tnd.parse_post(p)
        r = enrich(rev, p.get("plaintext"), archive)
        if not seeding:
            if tg:
                msg = send_card(tg, channel, r)
                r["tg_channel_msg"] = msg["message_id"]
            else:
                print("----\n" + card.caption(r) + "\n" + json.dumps(card.buttons(r), ensure_ascii=False))
        reviews.append(r)
        if r["id"] not in arch_ids:
            archive.append(archive_entry(r))
            arch_ids.add(r["id"])
        # save after every review so a crash later never re-posts this one
        save("reviews.json", reviews)
        save("archive.json", archive)

    if new or seeding or not state.get("channel_pinned_id"):
        text = card.pinned_text(reviews)
        if tg:
            if state.get("channel_pinned_id"):
                tg.edit_message(channel, state["channel_pinned_id"], text)
            else:
                msg = tg.send_message(channel, text, silent=True)
                tg.pin(channel, msg["message_id"])
                state["channel_pinned_id"] = msg["message_id"]
        else:
            print("---- pinned ----\n" + text)
    state["seeded"] = True
    save("reviews.json", reviews)
    save("archive.json", archive)
    if MODE == "run":
        save("state.json", state)


if __name__ == "__main__":
    main()
