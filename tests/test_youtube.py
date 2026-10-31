"""New reviews from YouTube: parsing video descriptions and deciding what each hourly run adds."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from lmn import check, tnd, youtube

NOW = datetime(2026, 10, 31, 21, 0, tzinfo=timezone.utc)

HMLTD = """Listen: https://hmltd.bandcamp.com/album/fangs

At the very least, FANGS isn’t a boring listen.

More rock reviews: https://youtube.com/playlist?list=PLP4CSgl7K7ori6-Iz-AWcX561iWCfapt_

===================================
Subscribe: http://bit.ly/1pBqGCN

Videos edited by Jeremy and Anthony / posted by austen
===================================

FAV TRACKS: UMAMI, CLOSE TO YOU, SHUDDER

LEAST FAV TRACK: CHATEAU VAMP FREESTYLE

HMLTD - FANGS / 2026 / LUCKY NUMBER / ART ROCK, DARKWAVE, NEW RAVE

5/10

Y'all know this is just my opinion, right?"""


def desc(meta, score, fav="FAV TRACKS: A, B", signoff="Y'all know this is just my opinion, right?", listen="https://example.com"):
    return f"Listen: {listen}\n\nTagline.\n\n===\nVideos edited by Jeremy and Anthony / posted by austen\n===\n\n{fav}\n\n{meta}\n\n{score}\n\n{signoff}"


def video(vid, title, description, hours_ago):
    return {"video_id": vid, "title": title, "desc": description,
            "published": (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z"), "thumb": None}


def site_post(pid, title, video_id=None, days_ago=1.0, tags=("Album Reviews", "7/10")):
    published = (NOW - timedelta(days=days_ago)).isoformat()
    return {"id": pid, "title": title, "slug": pid, "url": f"https://theneedledrop.com/album-reviews/{pid}/", "published_at": published,
            "canonical_url": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
            "tags": [{"name": t} for t in tags], "plaintext": "transcript"}


class DescriptionTest(unittest.TestCase):
    def test_regular_review(self):
        d = youtube.parse_description(HMLTD)
        self.assertEqual((d["score"], d["year"], d["label"]), (5, 2026, "LUCKY NUMBER"))
        self.assertEqual(d["genres"], ["art rock", "darkwave", "new rave"])
        self.assertEqual(d["fav_tracks"], ["UMAMI", "CLOSE TO YOU", "SHUDDER"])
        self.assertEqual(d["least_fav_track"], "CHATEAU VAMP FREESTYLE")
        self.assertEqual(d["listen_url"], "https://hmltd.bandcamp.com/album/fangs")
        self.assertNotIn("guest", d)

    def test_verdict_variants(self):
        meta = "X - Y / 2026 / LABEL / ROCK"
        self.assertTrue(youtube.parse_description(desc(meta, "NOT GOOD/10"))["not_good"])
        self.assertTrue(youtube.parse_description(desc(meta, "NOT MUSIC/10"))["not_good"])
        self.assertTrue(youtube.parse_description(desc(meta, "NOT BAD/10"))["not_bad"])
        self.assertEqual(youtube.parse_description(desc(meta, "0/10", fav="FAV TRACKS: N/A"))["score"], 0)
        self.assertEqual(youtube.parse_description(desc(meta, "0/10", fav="FAV TRACKS: N/A"))["fav_tracks"], [])
        d = youtube.parse_description(desc(meta, "8/10 https://theneedledrop.com/loved-list/2026/"))
        self.assertEqual((d["score"], d.get("loved")), (8, True))
        d = youtube.parse_description(desc(meta, "GIGGENS LOVES IT/10\n\nALSO SO DOES ANTHONY: https://theneedledrop.com/loved-list/2026/",
                                           signoff="Y'all know this is just his opinion, right?"))
        self.assertTrue(d["guest"])
        self.assertIsNone(d.get("score"))
        d = youtube.parse_description(desc(meta, "", signoff="Y'all know this is just their opinion, right?"))
        self.assertTrue(d["guest"])

    def test_lowercase_and_semicolons(self):
        d = youtube.parse_description(desc("olivia rodrigo - you seem pretty sad / 2026 / geffen / alt-pop, new wave", "8/10",
                                           fav="fav tracks: drop dead; stupid song, the cure"))
        self.assertEqual(d["fav_tracks"], ["drop dead", "stupid song", "the cure"])
        self.assertEqual(d["genres"], ["alt-pop", "new wave"])

    def test_what_is_a_review(self):
        self.assertTrue(youtube.is_review({"title": "HMLTD - FANGS ALBUM REVIEW", "desc": HMLTD}))
        self.assertTrue(youtube.is_review({"title": "Tyga's $tarface is NOT MUSIC", "desc": desc("TYGA - $TARFACE / 2026 / EMPIRE / SLOP", "NOT MUSIC/10")}))
        self.assertFalse(youtube.is_review({"title": "Addressing My Most Hated Review", "desc": "Y'all know this is just my opinion, right?"}))
        self.assertFalse(youtube.is_review({"title": "Olivia Rodrigo, Chappell Roan | Weekly Track Roundup: 10/25/26", "desc": HMLTD}))

    def test_review_from_video(self):
        r = youtube.review_from_video(video("abcdefghijk", "HMLTD - FANGS ALBUM REVIEW", HMLTD, 46))
        self.assertEqual((r["id"], r["artist_name"], r["album"], r["score"]), ("abcdefghijk", "HMLTD", "FANGS", 5))
        self.assertEqual(r["listen_bandcamp"], "https://hmltd.bandcamp.com/album/fangs")
        self.assertEqual(r["url"], "https://www.youtube.com/watch?v=abcdefghijk")
        r = youtube.review_from_video(video("v2", "Zach Bryan - Young Manhood EP REVIEW", desc("ZACH BRYAN - YOUNG MANHOOD / 2026 / X / COUNTRY", "6/10"), 1))
        self.assertEqual((r["album"], r["type"]), ("Young Manhood", "ep"))
        r = youtube.review_from_video(video("v3", "Ken Carson's Xperiment is NOT BAD", desc("KEN CARSON - XPERIMENT / 2026 / OPIUM / TRAP", "NOT BAD/10"), 1))
        self.assertEqual((r["artist_name"], r["album"], r["not_bad"], r["not_good"]), ("Ken Carson", "Xperiment", True, False))
        r = youtube.review_from_video(video("v4", "The Garden  Bootleg  album review", desc("THE GARDEN - BOOTLEG / 2026 / EPITAPH / PUNK", "5/10"), 1))
        self.assertEqual((r["artist_name"], r["album"]), ("THE GARDEN", "BOOTLEG"))


class PlanTest(unittest.TestCase):
    def plan(self, posts, uploads, reviews=(), seeding=False):
        return youtube.plan(posts, uploads, list(reviews), seeding, now=NOW)

    def test_new_video_gets_a_card_old_one_goes_to_the_list_only(self):
        uploads = [video("hmltd000001", "HMLTD - FANGS ALBUM REVIEW", HMLTD, 46),
                   video("roundup0001", "A, B | Weekly Track Roundup: 10/25/26", "songs", 30),
                   video("avalanches1", "The Avalanches - No Bad Memories ALBUM REVIEW",
                         desc("THE AVALANCHES - NO BAD MEMORIES / 2026 / X / PLUNDERPHONICS", "7/10"), 8 * 24)]
        new, upgrades = self.plan([], uploads)
        self.assertEqual([(i["rev"]["id"], i["card"]) for i in new], [("avalanches1", False), ("hmltd000001", True)])
        self.assertEqual(upgrades, [])

    def test_site_post_later_only_links_the_transcript(self):
        r = youtube.review_from_video(video("hmltd000001", "HMLTD - FANGS ALBUM REVIEW", HMLTD, 46))
        new, upgrades = self.plan([site_post("ghost1", "HMLTD - FANGS", "hmltd000001")], [video("hmltd000001", "HMLTD - FANGS ALBUM REVIEW", HMLTD, 46)], [r])
        self.assertEqual(new, [])
        self.assertEqual([(old["id"], s["id"]) for old, s in upgrades], [("hmltd000001", "ghost1")])
        youtube.apply_upgrade(r, upgrades[0][1])
        self.assertEqual(r["tnd_url"], "https://theneedledrop.com/album-reviews/ghost1/")
        # and with YouTube down the site post is still recognised as the same review
        self.assertEqual(self.plan([site_post("ghost1", "HMLTD - FANGS", "hmltd000001")], None, [r])[0], [])

    def test_site_already_has_it_keeps_the_transcript(self):
        new, _ = self.plan([site_post("ghost1", "HMLTD - FANGS", "hmltd000001", days_ago=0.1)], [video("hmltd000001", "HMLTD - FANGS ALBUM REVIEW", HMLTD, 46)])
        self.assertEqual([(i["rev"]["id"], i["text"], i["card"]) for i in new], [("ghost1", "transcript", True)])
        self.assertEqual(new[0]["rev"]["published"][:13], (NOW - timedelta(hours=46)).isoformat()[:13])  # the video's date

    def test_site_only_reviews(self):
        uploads = [video("hmltd000001", "HMLTD - FANGS ALBUM REVIEW", HMLTD, 46)]
        staff = site_post("staff1", "TND Staff Album Review: ‘Hauntings’ by Richard Barbieri", None, days_ago=1)
        old_staff = site_post("staff2", "TND Staff Album Review: ‘Old’ by Someone", None, days_ago=10)
        old_video = site_post("ghost9", "Old - Album", "oldvideo001", days_ago=0.5)  # site is late: the video isn't among new uploads
        unrecognised = site_post("ghost8", "New - Album", "newvideo001", days_ago=0.2)
        uploads.append(video("newvideo001", "New - Album ALBUM REVIEW", "a description without the usual lines", 20))
        new, _ = self.plan([staff, old_staff, old_video, unrecognised], uploads)
        cards = {i["rev"]["id"]: i["card"] for i in new}
        self.assertEqual(cards, {"hmltd000001": True, "staff1": True, "staff2": False, "ghost9": False, "ghost8": True})

    def test_youtube_down_falls_back_to_the_site(self):
        new, _ = self.plan([site_post("g1", "A - B")], None)
        self.assertEqual([(i["rev"]["id"], i["card"]) for i in new], [("g1", True)])

    def test_seeding_posts_no_cards(self):
        new, _ = self.plan([site_post("g1", "A - B")], [video("hmltd000001", "HMLTD - FANGS ALBUM REVIEW", HMLTD, 2)], seeding=True)
        self.assertEqual({i["card"] for i in new}, {False})
        self.assertEqual(len(new), 2)


class HourlyRunWithYouTubeTest(unittest.TestCase):
    def setUp(self):
        from test_check import FakeTelegram, fake_enrich
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.data = Path(self.dir.name)
        self.posts, self.uploads, self.tg = [], [], FakeTelegram()
        for p in [mock.patch.object(check, "DATA", self.data), mock.patch.object(check, "MODE", "run"),
                  mock.patch.object(check, "Telegram", lambda: self.tg), mock.patch.object(check, "enrich", fake_enrich),
                  mock.patch.object(check, "owner_statuses", lambda: {}),
                  mock.patch.object(tnd, "fetch_posts", lambda **kw: {"posts": [dict(p) for p in self.posts]}),
                  mock.patch.object(tnd, "fetch_all_light", lambda: []),
                  mock.patch.object(youtube, "latest_uploads", lambda: [dict(u) for u in self.uploads]),
                  mock.patch.dict("os.environ", {"TELEGRAM_CHANNEL": "@test"})]:
            p.start()
            self.addCleanup(p.stop)

    def cards(self):
        return [t for t in self.tg.sent if "Свежие обзоры" not in t]

    def test_youtube_review_is_posted_once_and_linked_when_the_site_catches_up(self):
        now = datetime.now(timezone.utc)
        self.posts = [site_post("g0", "Old - One", days_ago=3) | {"published_at": (now - timedelta(days=3)).isoformat()}]
        check.main()  # seeding
        self.assertEqual(self.cards(), [])
        self.uploads = [{"video_id": "hmltd000001", "title": "HMLTD - FANGS ALBUM REVIEW", "desc": HMLTD,
                         "published": (now - timedelta(hours=40)).isoformat(), "thumb": None}]
        check.main()
        check.main()
        self.assertEqual(len(self.cards()), 1)
        self.assertIn("HMLTD — FANGS", self.cards()[0])
        self.posts.append(site_post("g1", "HMLTD - FANGS", "hmltd000001") | {"published_at": now.isoformat()})
        check.main()
        self.assertEqual(len(self.cards()), 1)
        saved = json.loads((self.data / "reviews.json").read_text())
        hm = next(r for r in saved if r["id"] == "hmltd000001")
        self.assertEqual(hm["tnd_url"], "https://theneedledrop.com/album-reviews/g1/")
        self.assertEqual(sum(1 for r in saved if r.get("video_id") == "hmltd000001"), 1)


if __name__ == "__main__":
    unittest.main()
