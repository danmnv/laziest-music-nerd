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
        with mock.patch.object(notes, "deezer_track", side_effect=[111, None]) as dz:
            out = notes.build(ups, archive, {})
        self.assertEqual(out["nat"]["fav"], [{"t": "EUCALYPTUS", "dz": 111}, {"t": "TROPIC MORNING NEWS", "dz": None}])
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


if __name__ == "__main__":
    unittest.main()
