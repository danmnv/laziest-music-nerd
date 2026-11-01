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
    def setUp(self):  # never the network: a track not on Deezer would ask Apple
        patcher = mock.patch.object(notes, "apple_track", return_value=0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_matches_archive_and_looks_up_once(self):
        archive = [{"id": "nat", "artist_name": "The National", "album": "First Two Pages of Frankenstein"}]
        ups = [{"id": "cuAbVa3NM5I", "title": "The National - First Two Pages of Frankenstein ALBUM REVIEW", "desc": DESC}]
        with mock.patch.object(notes, "deezer_track", side_effect=[111, 0]) as dz:
            out = notes.build(ups, archive, {})
        self.assertEqual(out["nat"]["fav"], [{"t": "EUCALYPTUS", "dz": 111}, {"t": "TROPIC MORNING NEWS", "dz": 0, "am": 0}])
        self.assertEqual(out["nat"]["video_id"], "cuAbVa3NM5I")
        with mock.patch.object(notes, "deezer_track") as dz:
            again = notes.build(ups, archive, out)
        dz.assert_not_called()  # both were looked up already, one simply isn't on Deezer
        self.assertEqual(again, out)

    def test_a_track_not_on_deezer_gets_apple_music_once(self):
        archive = [{"id": "nat", "artist_name": "The National", "album": "First Two Pages of Frankenstein"}]
        ups = [{"id": "v", "title": "The National - First Two Pages of Frankenstein ALBUM REVIEW", "desc": DESC}]
        with mock.patch.object(notes, "deezer_track", side_effect=[111, 0]), \
                mock.patch.object(notes, "apple_track", return_value="us/album/x/1?i=2") as am:
            out = notes.build(ups, archive, {})
        am.assert_called_once_with("The National", "TROPIC MORNING NEWS")
        self.assertEqual(out["nat"]["fav"][1], {"t": "TROPIC MORNING NEWS", "dz": 0, "am": "us/album/x/1?i=2"})
        with mock.patch.object(notes, "deezer_track") as dz, mock.patch.object(notes, "apple_track") as am:
            self.assertEqual(notes.build(ups, archive, out), out)
        am.assert_not_called()

    def test_albums_newest_first_with_a_limit_and_remembered(self):
        archive = [{"id": "a", "artist_name": "A", "album": "X", "published": "2020"}, {"id": "b", "artist_name": "B", "album": "Y", "published": "2021"},
                   {"id": "s", "artist_name": "C", "album": "Song", "published": "2022", "track": True}]
        b = {"dz": 9, "cv": "https://cdn/b.jpg"}
        with mock.patch.object(notes, "deezer_album", return_value=b) as da, mock.patch.object(notes.time, "sleep"):
            out = notes.albums(archive, {}, limit=1)
            self.assertEqual(out, {"b": b})
            da.reset_mock()
            da.return_value = 0
            self.assertEqual(notes.albums(archive, out, limit=5), {"b": b, "a": 0})
            da.assert_called_once_with("A", "X")

    def test_deezer_album_checks_the_artist_and_keeps_what_the_card_shows(self):
        search = {"data": [{"id": 1, "title": "Kid A", "artist": {"name": "Someone"}},
                           {"id": 2, "title": "Kid A", "artist": {"name": "Radiohead"}, "cover_xl": "https://cdn/s.jpg"}]}
        album = {"id": 2, "cover_xl": "https://cdn/kida.jpg", "release_date": "2000-10-02", "duration": 2995,
                 "tracks": {"data": [{"title": "Everything in Its Right Place", "duration": 251}, {"title": "Kid A", "duration": 284}]}}
        with mock.patch.object(notes.http, "get_json", side_effect=[search, album]) as g:
            out = notes.deezer_album("Radiohead", "Kid A", sleep=lambda s: None)
        self.assertEqual(g.call_args_list[1].args[0], "https://api.deezer.com/album/2")
        self.assertEqual(out, {"dz": 2, "cv": "https://cdn/kida.jpg", "y": "2000", "min": 50,
                               "t": [["Everything in Its Right Place", 251], ["Kid A", 284]]})
        with mock.patch.object(notes.http, "get_json", return_value={"data": []}):
            self.assertEqual(notes.deezer_album("Radiohead", "Kid A", sleep=lambda s: None), 0)
        with mock.patch.object(notes.http, "get_json", return_value={"error": {"code": 4, "message": "Quota limit exceeded"}}):
            self.assertIsNone(notes.deezer_album("Radiohead", "Kid A", sleep=lambda s: None))

    def test_no_lookups_after_the_deadline(self):
        archive = [{"id": "nat", "artist_name": "The National", "album": "First Two Pages of Frankenstein"}]
        ups = [{"id": "v", "title": "The National - First Two Pages of Frankenstein ALBUM REVIEW", "desc": DESC}]
        with mock.patch.object(notes, "deezer_track") as dz, mock.patch.object(notes, "deezer_album") as dc:
            out = notes.build(ups, archive, {}, deadline=1)  # long past
            self.assertEqual(notes.albums(archive, {}, deadline=1), {})
        dz.assert_not_called()
        dc.assert_not_called()
        self.assertEqual(out["nat"]["fav"], [{"t": "EUCALYPTUS"}, {"t": "TROPIC MORNING NEWS"}])

    def test_lookup_limit_leaves_the_rest_for_next_run(self):
        archive = [{"id": "nat", "artist_name": "The National", "album": "First Two Pages of Frankenstein"}]
        ups = [{"id": "v", "title": "The National - First Two Pages of Frankenstein ALBUM REVIEW", "desc": DESC}]
        with mock.patch.object(notes, "deezer_track", return_value=5):
            out = notes.build(ups, archive, {}, deezer_limit=1)
        self.assertEqual(out["nat"]["fav"], [{"t": "EUCALYPTUS", "dz": 5}, {"t": "TROPIC MORNING NEWS"}])


class AppleTrack(unittest.TestCase):
    def test_apple_track_checks_the_artist_and_keeps_the_path(self):
        res = {"results": [{"artistName": "Someone", "trackName": "Karma Police", "trackViewUrl": "https://music.apple.com/us/album/a/1?i=9&uo=4"},
                           {"artistName": "Radiohead", "trackName": "Karma Police", "trackViewUrl": "https://music.apple.com/us/album/ok/2?i=3&uo=4"}]}
        with mock.patch.object(notes.http, "get_json", return_value=res):
            self.assertEqual(notes.apple_track("Radiohead", "Karma Police", sleep=lambda s: None), "us/album/ok/2?i=3")
        with mock.patch.object(notes.http, "get_json", return_value={"results": []}):
            self.assertEqual(notes.apple_track("Radiohead", "Karma Police", sleep=lambda s: None), 0)
        with mock.patch.object(notes.http, "get_json", side_effect=OSError("down")):
            self.assertIsNone(notes.apple_track("Radiohead", "Karma Police", sleep=lambda s: None))


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
        with mock.patch.object(notes, "deezer_track", return_value=7) as dz, mock.patch.object(notes.time, "sleep"), \
                mock.patch.object(notes, "apple_track", return_value=0):  # never the network
            out = notes.build(ups, archive, old)
        self.assertEqual(dz.call_count, 1)
        self.assertEqual(out["nat"]["fav"], [{"t": "EUCALYPTUS", "dz": 7}, {"t": "TROPIC MORNING NEWS", "dz": 0, "am": 0}])


if __name__ == "__main__":
    unittest.main()
