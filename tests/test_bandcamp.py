import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lmn import bandcamp, http

PAGE = '<div data-tralbum="{&quot;current&quot;:{&quot;title&quot;:&quot;Dopamine Chamber&quot;}}"></div>'


class Slugs(unittest.TestCase):
    def test_as_bandcamp_makes_them(self):
        self.assertEqual(bandcamp.slugs("Dopamine Chamber"), ["dopamine-chamber"])
        self.assertEqual(bandcamp.slugs("It's a Style Sport"), ["its-a-style-sport"])
        self.assertEqual(bandcamp.slugs("Salt & Pepper"), ["salt-and-pepper", "salt-pepper"])
        self.assertEqual(bandcamp.slugs("Café Ünïcode!"), ["cafe-unicode"])


class Labels(unittest.TestCase):
    def test_labels(self):
        from lmn import card
        self.assertEqual(card.bandcamp_label("https://a.bandcamp.com/"), "Bandcamp · артист")
        self.assertEqual(card.bandcamp_label("https://a.bandcamp.com/album/x"), "Bandcamp")
        self.assertEqual(card.bandcamp_label("https://bandcamp.com/search?q=x"), "🔎 Bandcamp")


class Find(unittest.TestCase):
    RG = {"rg_id": "rg", "artist_id": "art", "releases": ["r1"]}
    ARTIST = {"relations": [{"url": {"resource": "https://fontainesdc.bandcamp.com/"}}]}

    def test_the_releases_own_link_first(self):
        with mock.patch.object(bandcamp.musicbrainz, "find_release_group", return_value=self.RG), \
                mock.patch.object(bandcamp.musicbrainz, "release_details", return_value={"bandcamp": "http://label.bandcamp.com/album/y"}), \
                mock.patch.object(bandcamp.musicbrainz, "_get") as mb:
            self.assertEqual(bandcamp.find("X", "Y", {}), "https://label.bandcamp.com/album/y")
        mb.assert_not_called()

    def test_then_a_checked_album_page_on_the_artists_bandcamp(self):
        cache = {}
        with mock.patch.object(bandcamp.musicbrainz, "find_release_group", return_value=self.RG), \
                mock.patch.object(bandcamp.musicbrainz, "release_details", return_value={"bandcamp": None}), \
                mock.patch.object(bandcamp.musicbrainz, "_get", return_value=self.ARTIST) as mb, \
                mock.patch.object(bandcamp.http, "request", return_value=PAGE) as get:
            self.assertEqual(bandcamp.find("Fontaines D.C.", "Dopamine Chamber", cache), "https://fontainesdc.bandcamp.com/album/dopamine-chamber")
            bandcamp.find("Fontaines D.C.", "Dopamine Chamber", cache)
        self.assertEqual(mb.call_count, 1)  # the artist's links once a run
        get.assert_called_with("https://fontainesdc.bandcamp.com/album/dopamine-chamber", retries=1)

    def test_a_page_of_another_album_gives_the_artists_page(self):
        with mock.patch.object(bandcamp.musicbrainz, "find_release_group", return_value=self.RG), \
                mock.patch.object(bandcamp.musicbrainz, "release_details", return_value={"bandcamp": None}), \
                mock.patch.object(bandcamp.musicbrainz, "_get", return_value=self.ARTIST), \
                mock.patch.object(bandcamp.http, "request", return_value=PAGE.replace("Dopamine Chamber", "Other")):
            self.assertEqual(bandcamp.find("Fontaines D.C.", "Dopamine Chamber", {}), "https://fontainesdc.bandcamp.com/")
        with mock.patch.object(bandcamp.http, "request", side_effect=http.HttpError(404, "", "u")):
            self.assertIsNone(bandcamp.page_album("https://x.bandcamp.com/album/y"))

    def test_no_link(self):
        with mock.patch.object(bandcamp.musicbrainz, "find_release_group", return_value=self.RG), \
                mock.patch.object(bandcamp.musicbrainz, "_get", return_value={"relations": []}), \
                mock.patch.object(bandcamp.musicbrainz, "release_details", return_value={"bandcamp": "https://bandcamp.com/search?q=y"}):
            self.assertIsNone(bandcamp.find("X", "Y", {}))
        with mock.patch.object(bandcamp.musicbrainz, "find_release_group", return_value=None):
            self.assertIsNone(bandcamp.find("X", "Y", {}))


class Run(unittest.TestCase):
    def test_skips_known_links_and_remembers_misses(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            arch = [{"id": i, "artist_name": "A", "album": i, "published": f"2020-01-0{n}"} for n, i in enumerate(["own", "fan", "new", "miss"], 1)]
            arch.append({"id": "g", "artist_name": "A", "album": "G", "published": "2020-02-01", "guest": True})
            (p / "archive.json").write_text(json.dumps(arch))
            (p / "reviews.json").write_text(json.dumps([dict(arch[0], links={"bandcamp": "https://a.bandcamp.com/album/own"})]))
            (p / "notes.json").write_text(json.dumps({"fan": {"bc": "https://a.bandcamp.com/album/fan"}}))
            found = {"new": "https://a.bandcamp.com/album/new", "miss": None}
            with mock.patch.object(bandcamp, "DATA", p), mock.patch.dict(os.environ, {"BANDCAMP_LIMIT": "10"}), \
                    mock.patch.object(bandcamp, "find", side_effect=lambda artist, album, cache: found[album]) as f:
                bandcamp.run()
                self.assertEqual(sorted(c.args[1] for c in f.call_args_list), ["miss", "new"])
                out = json.loads((p / "bandcamp.json").read_text())
                self.assertEqual(out["new"]["u"], "https://a.bandcamp.com/album/new")
                self.assertEqual(out["miss"]["u"], 0)
                f.reset_mock()
                bandcamp.run()  # a miss waits RECHECK_DAYS
                f.assert_not_called()

    def test_an_artists_page_is_marked_and_looked_up_again_later(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "archive.json").write_text(json.dumps([{"id": "r", "artist_name": "A", "album": "R", "published": "2020-01-01"}]))
            with mock.patch.object(bandcamp, "DATA", p), \
                    mock.patch.object(bandcamp, "find", return_value="https://a.bandcamp.com/") as f:
                bandcamp.run()
                self.assertEqual(json.loads((p / "bandcamp.json").read_text())["r"]["root"], 1)
                f.reset_mock()
                bandcamp.run()
                f.assert_not_called()  # waits RECHECK_DAYS

    def test_a_new_review_is_looked_up_again_after_a_week(self):
        from datetime import datetime, timezone
        now = datetime(2026, 11, 10, tzinfo=timezone.utc)
        self.assertTrue(bandcamp.due({"u": 0, "checked": "2026-11-03"}, now, "2026-11-01"))
        self.assertFalse(bandcamp.due({"u": 0, "checked": "2026-11-05"}, now, "2026-11-01"))
        self.assertTrue(bandcamp.due({"u": "https://a.bandcamp.com/", "root": 1, "checked": "2026-11-03"}, now, "2026-11-01"))
        self.assertFalse(bandcamp.due({"u": 0, "checked": "2026-11-03"}, now, "2019-11-01"))  # an old one: 90 days
        self.assertFalse(bandcamp.due({"u": "https://a.bandcamp.com/album/x", "checked": "2020-01-01"}, now, "2019-11-01"))

if __name__ == "__main__":
    unittest.main()
