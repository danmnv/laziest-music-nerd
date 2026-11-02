"""One-off: edit every channel post into the current card layout (owner, 2026-11-02: «обнови старые» after the
channel card got action-only buttons and the links as text under the tracklist). Posts already in that layout are
skipped (the same fingerprint refresh.py keeps), so a second run edits nothing. An edit sends no notification.
Old reviews also get their Apple Music link, which new ones get when they are posted."""
import os
import time

from . import card, links, refresh
from .check import edit_card, load, save
from .telegram import Telegram

PAUSE_SEC = 3  # Telegram allows about 20 edits a minute in one chat; Apple's search about 20 requests a minute


def run(reviews, tg, channel, wl, sleep=time.sleep):
    edited = failed = 0
    for r in reviews:
        if not r.get("tg_channel_msg"):
            continue
        r.setdefault("links", {})
        if not r["links"].get("apple") and r.get("album"):
            apple = links.apple_album(r["artist_name"], r["album"])
            if apple:
                r["links"]["apple"] = apple
            sleep(PAUSE_SEC)
        now = refresh.shown(r, wl)
        if r.get("tg_shown") == now:
            continue
        try:
            edit_card(tg, channel, r, card.buttons(r, with_callbacks=wl))
            r["tg_shown"] = now
            edited += 1
        except RuntimeError as ex:  # one post that can't be edited doesn't stop the rest
            print(f"{r['id']}: {str(ex)[:200]}")
            failed += 1
        sleep(PAUSE_SEC)
    print(f"restyle: edited {edited}, failed {failed}, posts {sum(1 for r in reviews if r.get('tg_channel_msg'))}")
    return edited, failed


if __name__ == "__main__":
    reviews = load("reviews.json", [])
    try:
        run(reviews, Telegram(), os.environ["TELEGRAM_CHANNEL"].strip(), os.environ.get("WORKER_LIVE") == "1")
    finally:
        save("reviews.json", reviews)  # what was edited is remembered even if a later post failed
