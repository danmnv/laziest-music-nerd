"""Filling in a card after it went out: when, what, and editing the channel post."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from lmn import check, refresh, tnd, youtube
from test_check import FakeTelegram, fake_enrich
from test_youtube import HMLTD

NOW = datetime(2026, 10, 31, 21, 0, tzinfo=timezone.utc)


def rec(hours_ago, **kw):
    return dict({"id": "x", "published": (NOW - timedelta(hours=hours_ago)).isoformat()}, **kw)


class WhenTest(unittest.TestCase):
    def test_stages(self):
        self.assertIsNone(refresh.due(rec(10), NOW))
        r = rec(30)
        self.assertEqual(refresh.due(r, NOW), "1d")
        refresh.mark(r, "1d")
        self.assertIsNone(refresh.due(r, NOW))
        r = rec(80, refreshed=["1d"])
        self.assertEqual(refresh.due(r, NOW), "3d")
        r = rec(80)
        self.assertEqual(refresh.due(r, NOW), "3d")  # one lookup, not two in a row
        refresh.mark(r, "3d")
        self.assertEqual(r["refreshed"], ["1d", "3d"])
        self.assertIsNone(refresh.due(rec(8 * 24), NOW))

    def test_site_post_comes_first_at_any_age(self):
        r = rec(20 * 24, tnd_url="https://theneedledrop.com/x/", refreshed=["1d", "3d"])
        self.assertEqual(refresh.due(r, NOW), "site")
        refresh.mark(r, "site")
        self.assertIsNone(refresh.due(r, NOW))

    def test_found_late_skips_the_stages_behind_it(self):
        self.assertEqual(refresh.passed_stages(rec(30), NOW), ["1d"])
        self.assertEqual(refresh.passed_stages(rec(80), NOW), ["3d", "1d"])


class FillTest(unittest.TestCase):
    def test_only_empty_fields_are_filled(self):
        r = {"ai": {"brief": "Старый бриф"}, "links": {"bandcamp": "https://bandcamp.com/search?q=x", "ytmusic": "y"},
             "tracks": None, "artist": {}}
        fresh = {"ai": {"brief": "Новый бриф", "who": "Кто", "moods": ["для тусовки"]},
                 "links": {"bandcamp": "https://x.bandcamp.com/album/y", "songlink": "https://album.link/z", "ytmusic": "y2"},
                 "tracks": [{"title": "A", "sec": 60}], "duration_min": 40, "artist": {"mbid": "m"}, "previous": [{"album": "Old"}]}
        refresh.fill(r, fresh)
        self.assertEqual(r["ai"], {"brief": "Старый бриф", "who": "Кто", "moods": ["для тусовки"]})
        self.assertEqual(r["links"], {"bandcamp": "https://x.bandcamp.com/album/y", "ytmusic": "y", "songlink": "https://album.link/z"})
        self.assertEqual((r["duration_min"], r["artist"]["mbid"], r["previous"]), (40, "m", [{"album": "Old"}]))
        r["links"]["bandcamp"] = "https://real.bandcamp.com/album/a"
        refresh.fill(r, {"links": {"bandcamp": "https://bandcamp.com/search?q=a"}})
        self.assertEqual(r["links"]["bandcamp"], "https://real.bandcamp.com/album/a")

    def test_what_is_missing(self):
        full = {"ai": {"brief": "b"}, "tracks": [1], "duration_min": 3, "links": {"songlink": "s", "bandcamp": "https://a.bandcamp.com"}}
        self.assertEqual(refresh.missing(dict(full, tg_channel_msg=5)), [])
        self.assertEqual(refresh.missing(dict(full, ai={}, tg_channel_msg=5)), ["brief"])
        self.assertEqual(refresh.missing(dict(full, ai={})), [], "no Gemini for reviews without a card")


def later_enrich(rev, plaintext, archive, use_ai=True, **kw):
    """Like fake_enrich, but the sources now know more: a brief (when asked) and the tracklist."""
    r = fake_enrich(rev, plaintext, archive)
    if use_ai:
        r["ai"] = {"brief": f"Бриф из {'текста' if plaintext else 'видео'}."}
    r["tracks"], r["duration_min"] = [{"title": "UMAMI", "sec": 200}], 41
    r["links"] = {"songlink": "https://album.link/x"}
    return r


class HourlyRefreshTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.data = Path(self.dir.name)
        self.posts, self.uploads, self.tg = [], [], FakeTelegram()
        self.enrich = fake_enrich
        for p in [mock.patch.object(check, "DATA", self.data), mock.patch.object(check, "MODE", "run"),
                  mock.patch.object(check, "Telegram", lambda: self.tg),
                  mock.patch.object(check, "enrich", lambda *a, **kw: self.enrich(*a, **kw)),
                  mock.patch.object(check, "owner_statuses", lambda: {}),
                  mock.patch.object(tnd, "fetch_posts", lambda **kw: {"posts": [dict(p) for p in self.posts]}),
                  mock.patch.object(tnd, "fetch_all_light", lambda: []),
                  mock.patch.object(youtube, "latest_uploads", lambda: [dict(u) for u in self.uploads]),
                  mock.patch.dict("os.environ", {"TELEGRAM_CHANNEL": "@test"})]:
            p.start()
            self.addCleanup(p.stop)
        now = datetime.now(timezone.utc)
        check.main()  # seeding, empty
        self.uploads = [{"video_id": "hmltd000001", "title": "HMLTD - FANGS ALBUM REVIEW", "desc": HMLTD,
                         "published": (now - timedelta(hours=30)).isoformat(), "thumb": None}]
        check.main()  # the card goes out without a brief and a tracklist

    def saved(self):
        return next(r for r in json.loads((self.data / "reviews.json").read_text()) if r["video_id"] == "hmltd000001")

    def age(self, hours, **kw):
        rs = json.loads((self.data / "reviews.json").read_text())
        for r in rs:
            r.update(published=(datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(), **kw)
        (self.data / "reviews.json").write_text(json.dumps(rs))

    def edits(self):
        return getattr(self.tg, "texts", []) + getattr(self.tg, "captions", [])

    def card_edits(self):
        return [e for e in self.edits() if "Последние 30 обзоров" not in e[1]]

    def test_card_found_late_waits_for_the_next_stage_then_gets_what_was_missing(self):
        self.assertEqual(self.saved()["refreshed"], ["1d"])
        self.enrich = later_enrich
        check.main()
        self.assertEqual(self.card_edits(), [], "the 1-day lookup was the posting itself")
        self.age(80)
        check.main()
        [(msg, text)] = self.card_edits()
        self.assertEqual(msg, self.saved()["tg_channel_msg"])
        self.assertIn("Бриф из видео.", text)
        self.assertIn("41 мин", text)
        self.assertEqual(self.saved()["refreshed"], ["1d", "3d"])
        check.main()
        self.assertEqual(len(self.card_edits()), 1, "nothing more to do")

    def test_site_post_brings_the_transcript_to_gemini(self):
        self.enrich = later_enrich
        self.posts.append({"id": "g1", "title": "HMLTD - FANGS", "slug": "g1", "url": "https://theneedledrop.com/album-reviews/g1/",
                           "published_at": datetime.now(timezone.utc).isoformat(), "canonical_url": "",
                           "tags": [{"name": "Album Reviews"}, {"name": "5/10"}], "plaintext": "transcript"})
        check.main()
        [(_, text)] = self.card_edits()
        self.assertIn("Бриф из текста.", text)
        self.assertIn("site", self.saved()["refreshed"])

    def test_a_shown_brief_is_never_replaced(self):
        self.enrich = later_enrich
        self.age(80)
        check.main()
        self.enrich = lambda *a, **kw: dict(later_enrich(*a, **kw), ai={"brief": "Другой бриф."})
        self.age(80, refreshed=[], tnd_url="https://theneedledrop.com/x/", duration_min=None)  # something to look up again
        check.main()
        self.assertEqual(self.saved()["ai"]["brief"], "Бриф из видео.")

    def test_photo_post_is_edited_in_its_caption(self):
        self.enrich = later_enrich
        self.age(80, tg_kind=None)
        check.main()
        self.assertEqual(len(getattr(self.tg, "captions", [])), 1)
        self.assertEqual(self.saved()["tg_kind"], "photo")

    def test_a_post_that_cant_be_edited_is_given_up_after_three_hours(self):
        self.enrich = later_enrich

        def broken(chat_id, message_id, text, buttons=None):
            if "Последние 30 обзоров" in text:  # the pinned list is fine
                return
            self.tg.tries = getattr(self.tg, "tries", 0) + 1
            raise RuntimeError("Telegram editMessageText failed: Bad Request: message can't be edited")
        self.tg.edit_message = broken
        self.age(80)
        for _ in range(5):
            check.main()
        self.assertEqual(self.tg.tries, 3)
        self.assertEqual(self.saved()["ai"]["brief"], "Бриф из видео.", "what was found is kept for the site")


if __name__ == "__main__":
    unittest.main()
