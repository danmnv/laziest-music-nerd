"""Hourly job: find new TND album reviews, post a card to the channel, refresh the pinned 60-day list.

MODE=run   (default) normal hourly run
MODE=dry   no Telegram calls, print what would be sent
MODE=test  send the newest review's card to the owner's private chat only; nothing is saved
"""
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import card, http, refresh, tnd, youtube
from .colors import EMOJI, color
from .enrich import archive_entry, enrich
from .telegram import Telegram

DATA = Path(os.environ.get("DATA_DIR", "data"))
MODE = os.environ.get("MODE", "run")
# One slow Gemini call can take ~10 minutes with its retries, and the job is killed at 30.
# So each run handles at most a few new reviews and stops starting new ones after a time budget;
# the rest are picked up an hour later. Nothing is lost: a review counts as done only once it is saved.
MAX_NEW_PER_RUN = int(os.environ.get("MAX_NEW_PER_RUN") or 5)
TIME_BUDGET_SEC = int(os.environ.get("TIME_BUDGET_SEC") or 12 * 60)


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
            data = http.get_bytes(url)
        except Exception as ex:  # cover host is down or slow: try the next cover
            print(f"cover download failed ({type(ex).__name__}), trying next")
            continue
        try:
            return tg.send_photo_file(chat_id, data, text, kb)
        except RuntimeError as ex:
            # Telegram answered with an error, so nothing was posted and another cover is safe to try.
            # A timeout is different (the post may be out already) and is raised, not retried.
            print(f"Telegram rejected the cover ({str(ex)[:200]}), trying next")
    return tg.send_message(chat_id, text, kb)


def edit_card(tg, chat_id, r, kb):
    """Edit a posted card in place: the caption of a photo post, or the text of a post that went out without a cover."""
    text = card.caption(r)
    if r.get("tg_kind") != "text":
        try:
            tg.edit_caption(chat_id, r["tg_channel_msg"], text, kb)
            r["tg_kind"] = "photo"
            return
        except RuntimeError as ex:
            if "no caption" not in str(ex):
                raise
    tg.edit_message(chat_id, r["tg_channel_msg"], text, kb)
    r["tg_kind"] = "text"


def refresh_cards(reviews, posts, archive, tg, channel, started):
    """Cards already out: fill in what was missing and edit the channel post (see refresh.py). Returns how many were looked at."""
    wl = os.environ.get("WORKER_LIVE") == "1"
    texts = {p["id"]: p.get("plaintext") for p in posts}
    looked = 0
    for r in sorted(reviews, key=lambda x: refresh._ts(x["published"]), reverse=True):
        stage = refresh.due(r)
        if not stage:
            continue
        need = refresh.missing(r)
        stale = bool(r.get("tg_channel_msg")) and refresh.shown(r, wl) != r.get("tg_shown")
        if not (need or stale):  # complete and posted as it is: nothing to do, nothing to write
            continue
        if looked >= refresh.MAX_PER_RUN or time.monotonic() - started > TIME_BUDGET_SEC:
            print("refresh: the rest go next hour")
            break
        looked += 1
        if need:
            print(f"refresh {r['id']} ({stage}): looking up {', '.join(need)}")
            try:
                refresh.fill(r, enrich(r, texts.get(r.get("tnd_id") or r["id"]), archive, use_ai="brief" in need))
            except Exception as ex:
                print(f"refresh {r['id']}: enrich failed ({type(ex).__name__}: {str(ex)[:200]})")
        if r.get("tg_channel_msg") and refresh.shown(r, wl) != r.get("tg_shown"):
            if not tg:
                print("---- edit ----\n" + card.caption(r))
            else:
                try:
                    edit_card(tg, channel, r, card.buttons(r, with_callbacks=wl))
                    r["tg_shown"] = refresh.shown(r, wl)
                    print(f"refresh {r['id']}: channel post updated")
                except Exception as ex:
                    r["refresh_tries"] = r.get("refresh_tries", 0) + 1
                    print(f"refresh {r['id']}: editing the channel post failed ({str(ex)[:200]})")
                    if "message to edit not found" not in str(ex) and r["refresh_tries"] < refresh.MAX_TRIES:
                        continue  # what was found is kept; the post is edited next hour
        refresh.mark(r, stage)
    return looked


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


FOLLOW_WINDOW = timedelta(days=3)  # a review older than this is no longer news to its artist's followers


def tell_followers(reviews):
    """Hand the Worker each newly posted card, so it messages the people who follow that artist. Unsent ones (the
    Worker was down) are retried next hour; the Worker never messages a person twice about one review."""
    url, secret = worker()
    now = datetime.now(timezone.utc)
    todo = [r for r in reviews if r.get("tg_channel_msg") and not r.get("followers_told")
            and now - refresh._ts(r["published"]) <= FOLLOW_WINDOW]
    if not (url and todo):
        return False
    payload = [{"id": r["id"], "artist_name": r["artist_name"], "mbid": (r.get("artist") or {}).get("mbid"), "album": r["album"],
                "score": f"{EMOJI[color(r.get('score'), r.get('not_good'), r.get('classic'))]} {card.score_text(r)}",
                "msg": r["tg_channel_msg"]} for r in todo]
    try:
        d = json.loads(http.request(url + "/api/new-reviews", method="POST", json_body={"reviews": payload},
                                    headers={"Authorization": f"Bearer {secret}"}))
        if not d.get("ok"):
            raise ValueError("no ok")
    except Exception as ex:  # a Worker deployed before this feature answers any path with plain text
        print(f"worker: telling followers failed ({type(ex).__name__}); retrying next hour")
        return False
    for r in todo:
        r["followers_told"] = True
    print(f"followers: {len(todo)} new card(s), {d.get('sent', 0)} message(s) sent")
    return True


def bare(rev):
    """A card with only what TND itself gave us, for when enrichment crashed (empty field beats broken pipeline)."""
    r = dict(rev, ai={}, artist={}, links={}, previous=[], previous_unsure=0, covers=[c for c in [rev.get("thumb")] if c])
    if not r.get("artist_name"):
        r["artist_name"], r["album"] = r["title"], ""
    return r


def main():
    started = time.monotonic()
    reviews = load("reviews.json", [])
    state = load("state.json", {})
    archive = load("archive.json", [])
    for a in archive:  # old entries were saved before tnd.tidy_album existed
        tnd.tidy_entry(a)

    if not archive:
        print("building archive index from TND…")
        archive = [archive_entry(tnd.parse_post(p)) for p in tnd.fetch_all_light()]
        print(f"archive: {len(archive)} reviews")
    arch_ids = {a["id"] for a in archive}
    arch_videos = {a["video_id"] for a in archive if a.get("video_id")}

    seeding = not state.get("seeded")
    since = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    posts = tnd.fetch_posts(limit=50 if seeding else 15, with_text=True, since=since if seeding else None)["posts"]
    posts.sort(key=lambda p: p["published_at"])

    # New reviews are noticed on YouTube: the site posts them a day or more later, and skips some (see youtube.py).
    uploads = youtube.latest_uploads()

    if MODE == "test":
        # The newest review anywhere, even if it is already in the channel: a card for the owner only, nothing saved.
        everything, _ = youtube.plan(posts, uploads, [], seeding=False)
        item = everything[-1]
        r = next((x for x in reviews if x["id"] == item["rev"]["id"] or (x.get("video_id") and x.get("video_id") == item["rev"].get("video_id"))), None)
        r = r or enrich(item["rev"], item["text"], archive)
        tg = Telegram()
        send_card(tg, owner_chat(tg), r)
        print("test card sent to the owner's private chat:", r["title"])
        return

    tg = Telegram() if MODE == "run" else None
    channel = (os.environ.get("TELEGRAM_CHANNEL") or "").strip()
    new, upgrades = youtube.plan(posts, uploads, reviews, seeding)
    for old, site_rev in upgrades:
        print(f"site post appeared for {old['id']}: linking its transcript page")
        youtube.apply_upgrade(old, site_rev)
    if MODE == "dry" and os.environ.get("DRY_LIMIT"):
        new = new[-int(os.environ["DRY_LIMIT"]):]
    print(f"{len(new)} new review(s), {sum(i['card'] for i in new)} with a card{' (seeding)' if seeding else ''}")
    done, cards, failed = 0, 0, None
    for item in new:
        if item["card"] and cards >= MAX_NEW_PER_RUN:
            print(f"limit of {MAX_NEW_PER_RUN} cards per run reached; the rest go next hour")
            break
        if done and time.monotonic() - started > TIME_BUDGET_SEC:
            print("time budget used up; the rest go next hour")
            break
        rev = item["rev"]
        # Reviews without a card (seeding, or found too late) only fill the list and the site: no Gemini there,
        # its free daily limit is for new cards.
        try:
            r = enrich(rev, item["text"], archive, use_ai=item["card"])
        except Exception as ex:  # a broken source must not stop the card
            print(f"enrich failed for {rev['id']} ({type(ex).__name__}: {str(ex)[:200]}), posting a bare card")
            r = bare(rev)
        if item["card"]:
            cards += 1
            if tg:
                try:
                    msg = send_card(tg, channel, r)
                except Exception as ex:
                    # Not saved, so it is retried next hour. Stop here to keep the channel in publishing order.
                    failed = f"{type(ex).__name__}: {str(ex)[:300]}"
                    print(f"posting {rev['id']} failed: {failed}")
                    break
                r["tg_channel_msg"] = msg["message_id"]
                r["tg_kind"] = "photo" if msg.get("photo") else "text"
                r["tg_shown"] = refresh.shown(r, os.environ.get("WORKER_LIVE") == "1")
            else:
                print("----\n" + card.caption(r) + "\n" + json.dumps(card.buttons(r), ensure_ascii=False))
        r["refreshed"] = refresh.passed_stages(r)  # just looked up: a stage already behind it is not repeated
        reviews.append(r)
        done += 1
        if r["id"] not in arch_ids and not (r.get("video_id") and r["video_id"] in arch_videos):
            archive.append(archive_entry(r))
            arch_ids.add(r["id"])
            if r.get("video_id"):
                arch_videos.add(r["video_id"])
        # save after every review so a crash later never re-posts this one
        save("reviews.json", reviews)
        save("archive.json", archive)
    complete = done == len(new)
    new = new[:done]
    if not seeding and refresh_cards(reviews, posts, archive, tg, channel, started):
        save("reviews.json", reviews)
        save("archive.json", archive)
    if upgrades and not new:  # nothing else would save them
        save("reviews.json", reviews)

    items = card.list_items(reviews)
    list_changed = load("list.json", {}).get("items") != items
    if list_changed:  # otherwise every hourly run would commit a new timestamp
        save("list.json", {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "items": items})
    if new or seeding or list_changed or not state.get("channel_pinned_id"):
        text = card.render_list(items, owner_statuses())
        if tg:
            if state.get("channel_pinned_id"):
                try:
                    tg.edit_message(channel, state["channel_pinned_id"], text)
                except RuntimeError as ex:
                    if "message to edit not found" not in str(ex):
                        raise
                    print("pinned list was deleted in the channel; posting a new one")
                    state.pop("channel_pinned_id")
            if not state.get("channel_pinned_id"):
                msg = tg.send_message(channel, text, silent=True)
                tg.pin(channel, msg["message_id"])
                state["channel_pinned_id"] = msg["message_id"]
        else:
            print("---- pinned ----\n" + text)
    if tg and not seeding:
        tell_followers(reviews)
    if (new or seeding or list_changed) and tg:
        url, secret = worker()
        if url:
            try:
                http.request(url + "/api/refresh-lists", method="POST", json_body={"items": items}, headers={"Authorization": f"Bearer {secret}"})
            except Exception as ex:
                print(f"worker refresh failed: {type(ex).__name__}")
    if complete:  # an unfinished seeding run must not turn the remaining old reviews into channel cards
        state["seeded"] = True
    save("reviews.json", reviews)
    save("archive.json", archive)
    if MODE == "run":
        save("state.json", state)
    if failed:
        sys.exit(f"stopped: a card could not be posted ({failed}); it will be retried next hour")


if __name__ == "__main__":
    main()
