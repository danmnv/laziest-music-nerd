import unittest
from unittest import mock

from lmn import http, tnd, tnd_missing


def post(pid, title, tags, date="2015-06-20T17:08:57.000-04:00", slug=None):
    slug = slug or pid
    return {"id": pid, "title": title, "slug": slug, "published_at": date, "url": f"https://theneedledrop.com/{slug}/",
            "tags": [{"name": t, "slug": t.lower().replace("/", "").replace(" ", "-")} for t in tags]}


ARCHIVE = [
    {"id": "old1", "url": "https://theneedledrop.com/album-reviews/x/", "published": "2015-02-11T15:00:00Z", "artist_name": "Father John Misty",
     "album": "I Love You, Honeybear", "score": 8, "not_good": False, "classic": False, "guest": False, "genres": []},
]


class Missing(unittest.TestCase):
    def test_reviews_without_the_tag_are_found(self):
        posts = [
            post("p1", "Kendrick Lamar - To Pimp A Butterfly", ["abstract hip hop", "album", "jazz rap", "Kendrick Lamar", "10/10", "top dawg entertainment"]),
            post("p2", 'Co La - "Suffering (Tuesday)"', ["electronic", "track"]),              # a track pick: no verdict
            post("p3", "Kendrick Lamar - \"Alright\" (Video)", ["hip hop", "video"]),            # a video post
            post("p4", "Father John Misty - I Love You, Honeybear", ["folk rock", "8/10"]),      # the archive has it under another id
            post("old1", "Father John Misty - I Love You, Honeybear", ["8/10"]),                 # the archive has this very post
            post("p5", "Tyga's The Gold Album is NOT GOOD", ["hip hop", "not good"]),
            post("p6", "Tame Impala - Currents", ["psychedelic pop", "9/10"], date="2015-07-20T12:00:00.000-04:00"),
            post("p7", "Tame Impala - Currents", ["psychedelic pop", "9/10"], date="2015-07-21T12:00:00.000-04:00"),  # posted twice
            post("p8", "YUNOREVIEW: June 2015", ["yunoreview"]),
            post("p9", "Weekly Track Roundup", ["7/10"]),                                        # no "Artist - Album"
        ]
        new, n = tnd_missing.missing(posts, ARCHIVE)
        self.assertEqual([a["id"] for a in new], ["p1", "p5", "p6"])
        self.assertEqual((n["posts"], n["reviews"], n["known"], n["new"]), (10, 6, 3, 3))
        tpab = new[0]
        self.assertEqual((tpab["artist_name"], tpab["album"], tpab["score"]), ("Kendrick Lamar", "To Pimp A Butterfly", 10))
        self.assertEqual(tpab["published"], "2015-06-20T21:08:57Z")  # UTC with Z, like the rest of the archive
        self.assertEqual(tpab["url"], "https://theneedledrop.com/p1/")
        self.assertIn("jazz rap", tpab["genres"])
        self.assertNotIn("10/10", tpab["genres"])
        self.assertTrue(new[1]["not_good"])
        self.assertEqual(set(tpab), set(ARCHIVE[0]) | {"video_id"})  # the same fields as an archive entry
        self.assertEqual(tnd_missing.badge(tpab), "10/10")
        self.assertEqual(tnd_missing.badge(new[1]), "NOT GOOD")

    def test_walk_pages_and_drops_tagged_posts(self):
        pages = {1: {"posts": [post("a", "A - B", ["9/10"]), post("b", "C - D", ["album reviews"])], "meta": {"pagination": {"next": 2, "total": 3}}},
                 2: {"posts": [post("c", "E - F", ["7/10"])], "meta": {"pagination": {"next": None, "total": 3}}}}
        asked = []

        def fetch(limit, page, filter):
            asked.append((page, filter))
            return pages[page]

        with mock.patch.object(tnd, "fetch_posts", fetch):
            got = list(tnd_missing.walk(since="2015-02-01", until="2015-09-01", sleep=lambda s: None, log=lambda m: None))
        self.assertEqual([p["id"] for p in got], ["a", "c"])
        self.assertEqual(asked, [(1, "tag:-album-reviews+published_at:>'2015-02-01'+published_at:<'2015-09-01'"),
                                 (2, "tag:-album-reviews+published_at:>'2015-02-01'+published_at:<'2015-09-01'")])

    def test_walk_without_the_filter_when_the_site_refuses_it(self):
        asked = []

        def fetch(limit, page, filter):
            asked.append(filter)
            if "tag:-" in filter:
                raise http.HttpError(400, "bad filter", "u")
            return {"posts": [post("a", "A - B", ["9/10"]), post("b", "C - D", ["album reviews"])], "meta": {"pagination": {"next": None, "total": 2}}}

        with mock.patch.object(tnd, "fetch_posts", fetch):
            got = list(tnd_missing.walk(sleep=lambda s: None, log=lambda m: None))
        self.assertEqual([p["id"] for p in got], ["a"])
        self.assertEqual(asked, ["tag:-album-reviews", ""])

    def test_another_failure_is_not_swallowed(self):
        def fetch(limit, page, filter):
            raise http.HttpError(503, "down", "u")

        with mock.patch.object(tnd, "fetch_posts", fetch):
            with self.assertRaises(http.HttpError):
                list(tnd_missing.walk(sleep=lambda s: None, log=lambda m: None))


if __name__ == "__main__":
    unittest.main()
