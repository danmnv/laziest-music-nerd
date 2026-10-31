"""Hourly job: find new TND album reviews, post a card to the channel, refresh the pinned 60-day list.

MODE=run   (default) normal hourly run
MODE=dry   no Telegram calls, print what would be sent
MODE=test  send the newest review's card to the owner's private chat only; nothing is saved
"""
import hashlib
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
    known = worker_owner_id()
    if known:
        return known
    # Works only until the Worker is deployed: with a webhook set, Telegram answers getUpdates with 409.
    ups = tg.call("getUpdates", limit=100)
    chats = {u["message"]["chat"]["id"] for u in ups if u.get("message", {}).get("chat", {}).get("type") == "private"}
    if len(chats) != 1:
        sys.exit(f"test mode: expected exactly one private chat with the bot, found {len(chats)}. Set TELEGRAM_OWNER_ID.")
    return chats.pop()


def worker():
    f = DATA / "worker_url.txt"
    url = f.read_text().strip() if f.exists() else None
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not (url and token):
        return None, None
    # same derivation as the deploy workflow, so no extra secret is needed
    return url.rstrip("/"), hashlib.sha256(f"{token}:actions".encode()).hexdigest()[:48]


def worker_owner_id():
    """The owner's Telegram id as the Worker knows it (it found it on the first deploy). None if there's no Worker yet."""
    url, secret = worker()
    if not url:
        return None
    try:
        return http.get_json(url + "/api/owner/id", headers={"Authorization": f"Bearer {secret}"}).get("owner_id")
    except Exception as ex:
        print(f"worker owner id unavailable: {type(ex).__name__}")
        return None


def owner_statuses():
    """The owner's marks for the channel's pinned list, if the Worker is up and the 'show in channel' switch is on."""
    url, secret = worker()
    if not url:
        return {}
    try:
        d = http.get_json(url + "/api/owner/channel-marks", headers={"Authorization": f"Bearer {secret}"})
        return d.get("marks", {})
    except Exception as ex:
        print(f"worker marks unavailable: {type(ex).__name__}")
        return {}


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
    channel = (os.environ.get("TELEGRAM_CHANNEL") or "").strip()
    new = [p for p in posts if p["id"] not in known]
    if MODE == "dry" and os.environ.get("DRY_LIMIT"):
        new = new[-int(os.environ["DRY_LIMIT"]):]
    print(f"{len(new)} new review(s){' (seeding, no cards)' if seeding else ''}")
    for p in new:
        rev = tnd.parse_post(p)
        # Seeding fills the list and the site with ~50 older reviews: no Gemini there, its free daily limit is for new cards.
        r = enrich(rev, p.get("plaintext"), archive, use_ai=not seeding)
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

    items = card.list_items(reviews)
    save("list.json", {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "items": items})
    if new or seeding or not state.get("channel_pinned_id"):
        text = card.render_list(items, owner_statuses())
        if tg:
            if state.get("channel_pinned_id"):
                tg.edit_message(channel, state["channel_pinned_id"], text)
            else:
                msg = tg.send_message(channel, text, silent=True)
                tg.pin(channel, msg["message_id"])
                state["channel_pinned_id"] = msg["message_id"]
        else:
            print("---- pinned ----\n" + text)
    if (new or seeding) and tg:
        url, secret = worker()
        if url:
            try:
                http.request(url + "/api/refresh-lists", method="POST", json_body={"items": items}, headers={"Authorization": f"Bearer {secret}"})
            except Exception as ex:
                print(f"worker refresh failed: {type(ex).__name__}")
    state["seeded"] = True
    save("reviews.json", reviews)
    save("archive.json", archive)
    if MODE == "run":
        save("state.json", state)


if __name__ == "__main__":
    main()
