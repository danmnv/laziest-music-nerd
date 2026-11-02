import datetime
import unittest
from unittest import mock

from lmn import apple, links

DAY = datetime.date(2026, 11, 2)


class AppleTest(unittest.TestCase):
    def test_find_exact_album_not_the_single_and_tells_a_miss_from_a_failure(self):
        res = {"results": [{"artistName": "Kendrick Lamar", "collectionName": "GNX - Single", "collectionViewUrl": "https://music.apple.com/us/album/s/1?uo=4"},
                           {"artistName": "Kendrick Lamar", "collectionName": "GNX", "collectionViewUrl": "https://music.apple.com/us/album/gnx/2?uo=4"}]}
        with mock.patch.object(links.http, "get_json", return_value=res):
            self.assertEqual(links.apple_find("Kendrick Lamar", "GNX"), "https://music.apple.com/us/album/gnx/2")
            self.assertEqual(links.apple_find("Kendrick Lamar", "DAMN."), 0)
        with mock.patch.object(links.http, "get_json", side_effect=links.http.HttpError(429, "rate limit", "u")):
            self.assertIsNone(links.apple_find("Kendrick Lamar", "GNX"))
            self.assertIsNone(links.apple_album("Kendrick Lamar", "GNX"))
        nas = {"results": [{"artistName": "Nas", "collectionName": "Light-Years", "collectionViewUrl": "https://music.apple.com/us/album/l/3"}]}
        with mock.patch.object(links.http, "get_json", return_value=nas):  # a collaboration: under one of its artists
            self.assertEqual(links.apple_find("Nas & DJ Premier", "Light-Years"), "https://music.apple.com/us/album/l/3")

    def test_run_newest_first_keeps_answers_and_asks_misses_again_when_due(self):
        archive = [{"id": "old", "artist_name": "A", "album": "X", "published": "2020-01-01"},
                   {"id": "new", "artist_name": "B", "album": "Y", "published": "2026-10-30"},
                   {"id": "s", "artist_name": "C", "album": "Song", "published": "2026-10-31", "track": True}]
        sleep = mock.Mock()
        with mock.patch.object(links, "apple_find", side_effect=["https://am/y", 0]) as f:
            out = apple.run(archive, {}, today=DAY, sleep=sleep)
        self.assertEqual(out, {"new": "https://am/y", "old": {"miss": "2026-11-02"}})
        self.assertEqual([c.args for c in f.call_args_list], [("B", "Y"), ("A", "X")])
        sleep.assert_called_once_with(apple.SLEEP)
        with mock.patch.object(links, "apple_find") as f:  # found and not yet due: nothing asked
            self.assertEqual(apple.run(archive, out, today=DAY, sleep=sleep), out)
            f.assert_not_called()
        with mock.patch.object(links, "apple_find", return_value=None):  # failed: the old answer stays
            self.assertEqual(apple.run(archive, {"old": {"miss": "2026-01-01"}}, today=DAY, sleep=sleep), {"old": {"miss": "2026-01-01"}})
        with mock.patch.object(links, "apple_find", return_value="https://am/x"):  # out of lookups: the old answer stays
            self.assertEqual(apple.run(archive, {"old": 0}, limit=1, today=DAY, sleep=sleep), {"new": "https://am/x", "old": 0})


    def test_a_refusing_apple_gets_a_minute_then_the_run_stops(self):
        archive = [{"id": f"a{i}", "artist_name": "A", "album": f"X{i}", "published": f"2020-01-{i + 1:02d}"} for i in range(20)]
        sleep = mock.Mock()
        with mock.patch.object(links, "apple_find", return_value=None) as f:
            self.assertEqual(apple.run(archive, {}, today=DAY, sleep=sleep), {})
        self.assertEqual(f.call_count, apple.GIVE_UP)
        self.assertIn(mock.call(60), sleep.call_args_list)


if __name__ == "__main__":
    unittest.main()
