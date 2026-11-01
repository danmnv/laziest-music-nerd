import unittest
from unittest import mock

from lmn import notes

DESC = """Listen: https://thenational.bandcamp.com/album/x

If you found The National's previous music too colorful, the band's got you covered.

More rock reviews: https://www.youtube.com/playlist?list=x

===================================
Subscribe: http://bit.ly/1pBqGCN
===================================

FAV TRACKS: EUCALYPTUS, TROPIC MORNING NEWS

LEAST FAV TRACK: ALIEN

THE NATIONAL - FIRST TWO PAGES OF FRANKENSTEIN / 2023 / 4AD / INDIE ROCK

6/10
"""


class Blurb(unittest.TestCase):
    def test_first_prose_line(self):
        self.assertEqual(notes.blurb(DESC), "If you found The National's previous music too colorful, the band's got you covered.")

    def test_old_boilerplate_is_skipped(self):
        self.assertIsNone(notes.blurb("Listen: http://x\nWhat do you think of this album? Love it? Hate it?\nhttp://theneedledrop.com"))
        long = "word " * 100
        self.assertTrue(notes.blurb(long).endswith("…"))


class Build(unittest.TestCase):
    def test_matches_archive_and_looks_up_once(self):
        archive = [{"id": "nat", "artist_name": "The National", "album": "First Two Pages of Frankenstein"}]
        ups = [{"id": "cuAbVa3NM5I", "title": "The National - First Two Pages of Frankenstein ALBUM REVIEW", "desc": DESC}]
        with mock.patch.object(notes, "deezer_track", side_effect=[111, 0]) as dz:
            out = notes.build(ups, archive, {})
        self.assertEqual(out["nat"]["fav"], [{"t": "EUCALYPTUS", "dz": 111}, {"t": "TROPIC MORNING NEWS", "dz": 0}])
        self.assertEqual(out["nat"]["video_id"], "cuAbVa3NM5I")
        with mock.patch.object(notes, "deezer_track") as dz:
            again = notes.build(ups, archive, out)
        dz.assert_not_called()  # both were looked up already, one simply isn't on Deezer
        self.assertEqual(again, out)

    def test_lookup_limit_leaves_the_rest_for_next_run(self):
        archive = [{"id": "nat", "artist_name": "The National", "album": "First Two Pages of Frankenstein"}]
        ups = [{"id": "v", "title": "The National - First Two Pages of Frankenstein ALBUM REVIEW", "desc": DESC}]
        with mock.patch.object(notes, "deezer_track", return_value=5):
            out = notes.build(ups, archive, {}, deezer_limit=1)
        self.assertEqual(out["nat"]["fav"], [{"t": "EUCALYPTUS", "dz": 5}, {"t": "TROPIC MORNING NEWS"}])


class DeezerTrack(unittest.TestCase):
    def test_plain_words_then_track_field_and_the_artist_is_checked(self):
        other = {"data": [{"id": 1, "title": "Karma Police", "artist": {"name": "Someone Else"}}]}
        hit = {"data": [{"id": 138539981, "title": "Karma Police", "artist": {"name": "Radiohead"}}]}
        with mock.patch.object(notes.http, "get_json", side_effect=[other, hit]) as g:
            self.assertEqual(notes.deezer_track("Radiohead", "KARMA POLICE"), 138539981)
        urls = [c.args[0] for c in g.call_args_list]
        self.assertIn("q=Radiohead%20KARMA%20POLICE", urls[0])
        self.assertIn("q=track%3A%22KARMA%20POLICE%22", urls[1])
        self.assertNotIn("artist%3A", "".join(urls))  # Deezer answers nothing for artist:"..." in a track search
        with mock.patch.object(notes.http, "get_json", return_value={"data": []}):
            self.assertEqual(notes.deezer_track("A", "B"), 0)
        with mock.patch.object(notes.http, "get_json", return_value={"error": {"code": 4, "message": "Quota limit exceeded"}}):
            self.assertIsNone(notes.deezer_track("A", "B"))

    def test_old_none_is_looked_up_again(self):
        archive = [{"id": "nat", "artist_name": "The National", "album": "First Two Pages of Frankenstein"}]
        ups = [{"id": "cuAbVa3NM5I", "title": "The National - First Two Pages of Frankenstein ALBUM REVIEW", "desc": DESC}]
        old = {"nat": {"fav": [{"t": "EUCALYPTUS", "dz": None}, {"t": "TROPIC MORNING NEWS", "dz": 0}]}}
        with mock.patch.object(notes, "deezer_track", return_value=7) as dz, mock.patch.object(notes.time, "sleep"):
            out = notes.build(ups, archive, old)
        self.assertEqual(dz.call_count, 1)
        self.assertEqual(out["nat"]["fav"], [{"t": "EUCALYPTUS", "dz": 7}, {"t": "TROPIC MORNING NEWS", "dz": 0}])


if __name__ == "__main__":
    unittest.main()
