"""The hourly run against fake TND and Telegram: no duplicate cards, no lost reviews."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from lmn import check, tnd


def tnd_post(i, days_ago=1):
    published = (datetime.now(timezone.utc) - timedelta(days=days_ago, minutes=i)).isoformat()
    return {"id": f"post{i:02d}", "title": f"Artist {i} - Album {i}", "slug": f"a{i}",
            "url": f"https://theneedledrop.com/album-reviews/a{i}/", "published_at": published,
            "canonical_url": "", "tags": [{"name": "Album Reviews"}, {"name": "7/10"}, {"name": "art pop"}],
            "plaintext": "text"}


class FakeTelegram:
    def __init__(self, fail_on=()):
        self.sent, self.edited, self.pinned, self.fail_on, self.next_id = [], [], [], set(fail_on), 100

    def send_message(self, chat_id, text, buttons=None, silent=False):
        if any(f in text for f in self.fail_on):
            raise RuntimeError("Telegram sendMessage failed: Bad Request")
        self.next_id += 1
        self.sent.append(text)
        return {"message_id": self.next_id}

    def send_photo_file(self, *a, **kw):
        raise AssertionError("no covers in these tests")

    def edit_message(self, chat_id, message_id, text, buttons=None):
        self.edited.append(message_id)
        self.texts = getattr(self, "texts", []) + [(message_id, text)]

    def edit_caption(self, chat_id, message_id, caption, buttons=None):
        self.captions = getattr(self, "captions", []) + [(message_id, caption)]

    def pin(self, chat_id, message_id):
        self.pinned.append(message_id)


def fake_enrich(rev, plaintext, archive, **kw):  # **kw: use_ai etc.
    return dict(rev, ai={}, artist={}, links={}, previous=[], previous_unsure=0, covers=[])


class HourlyRunTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.data = Path(self.dir.name)
        self.posts = []
        self.tg = FakeTelegram()
        patches = [
            mock.patch.object(check, "DATA", self.data),
            mock.patch.object(check, "MODE", "run"),
            mock.patch.object(check, "Telegram", lambda: self.tg),
            mock.patch.object(check, "enrich", fake_enrich),
            mock.patch.object(check, "owner_statuses", lambda: {}),
            mock.patch.object(tnd, "fetch_posts", lambda **kw: {"posts": [dict(p) for p in self.posts]}),
            mock.patch.object(tnd, "fetch_all_light", lambda: []),
            mock.patch.dict("os.environ", {"TELEGRAM_CHANNEL": "@test"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.dir.cleanup)

    def run_once(self):
        check.main()

    def cards(self):
        return [t for t in self.tg.sent if "Свежие обзоры" not in t]

    def seed(self, n=2):
        self.posts = [tnd_post(i) for i in range(n)]
        self.run_once()
        self.assertEqual(self.cards(), [], "the first run only seeds, it posts no cards")

    def test_no_duplicates_across_runs(self):
        self.seed()
        self.posts.append(tnd_post(10, days_ago=0))
        self.run_once()
        self.run_once()
        self.assertEqual(len(self.cards()), 1)
        self.assertIn("Album 10", self.cards()[0])

    def test_enrich_crash_still_posts_a_bare_card(self):
        self.seed()
        self.posts.append(tnd_post(10, days_ago=0))
        with mock.patch.object(check, "enrich", side_effect=ValueError("bad JSON from MusicBrainz")):
            self.run_once()
        self.assertEqual(len(self.cards()), 1)
        self.assertIn("Artist 10 — Album 10", self.cards()[0])

    def test_failed_post_is_retried_once_and_earlier_ones_are_kept(self):
        self.seed()
        self.posts += [tnd_post(11, days_ago=0), tnd_post(10, days_ago=0)]  # 11 is older (minutes=i)
        self.tg.fail_on = {"Album 10"}
        with self.assertRaises(SystemExit):
            self.run_once()
        self.assertEqual([c.split("\n")[0] for c in self.cards()], ["<b>Artist 11 — Album 11</b>"])
        self.tg.fail_on = set()
        self.run_once()
        self.assertEqual([c.split("\n")[0] for c in self.cards()], ["<b>Artist 11 — Album 11</b>", "<b>Artist 10 — Album 10</b>"])

    def test_at_most_n_cards_per_run_rest_next_hour(self):
        self.seed()
        self.posts += [tnd_post(10 + i, days_ago=0) for i in range(7)]
        with mock.patch.object(check, "MAX_NEW_PER_RUN", 5):
            self.run_once()
            self.assertEqual(len(self.cards()), 5)
            self.run_once()
        self.assertEqual(len(self.cards()), 7)
        self.assertEqual(len({c.split("\n")[0] for c in self.cards()}), 7)

    def test_unfinished_seeding_never_posts_old_reviews(self):
        self.posts = [tnd_post(i) for i in range(4)]
        with mock.patch.object(check, "TIME_BUDGET_SEC", -1):  # budget is gone after the first review
            self.run_once()
        self.assertFalse(json.loads((self.data / "state.json").read_text()).get("seeded"))
        self.run_once()
        self.assertTrue(json.loads((self.data / "state.json").read_text())["seeded"])
        self.assertEqual(self.cards(), [])

    def test_quiet_hour_writes_nothing(self):
        self.seed()
        lst = json.loads((self.data / "list.json").read_text())
        (self.data / "list.json").write_text(json.dumps(dict(lst, updated="2026-01-01T00:00:00+00:00")))
        before = {p.name: p.read_text() for p in self.data.iterdir()}
        self.run_once()
        after = {p.name: p.read_text() for p in self.data.iterdir()}
        self.assertEqual(before, after, "an hour without new reviews must not create a commit")

    def test_deleted_pinned_list_is_recreated(self):
        self.seed()
        old_pin = json.loads((self.data / "state.json").read_text())["channel_pinned_id"]

        def gone(*a, **kw):
            raise RuntimeError("Telegram editMessageText failed: Bad Request: message to edit not found")
        self.tg.edit_message = gone
        self.posts.append(tnd_post(10, days_ago=0))
        self.run_once()
        new_pin = json.loads((self.data / "state.json").read_text())["channel_pinned_id"]
        self.assertNotEqual(old_pin, new_pin)
        self.assertEqual(self.tg.pinned[-1], new_pin)


if __name__ == "__main__":
    unittest.main()
