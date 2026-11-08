import datetime
import unittest
import urllib.parse
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


class BandcampLink(unittest.TestCase):
    def test_listen_line_on_bandcamp(self):
        self.assertEqual(notes.bandcamp(DESC), "https://thenational.bandcamp.com/album/x")
        self.assertIsNone(notes.bandcamp("Listen: https://open.spotify.com/album/x\n"))
        self.assertIsNone(notes.bandcamp("Listen: https://notbandcamp.com.evil.io/x\n"))
        self.assertIsNone(notes.bandcamp("Listen: https://bandcamp.com/search?q=x\n"))
        self.assertIsNone(notes.bandcamp("no listen line"))
        self.assertEqual(notes.bandcamp("Listen: http://x.bandcamp.com/album/y\n"), "https://x.bandcamp.com/album/y")


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
        self.assertEqual(out["nat"]["bc"], "https://thenational.bandcamp.com/album/x")
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
        with mock.patch.object(notes, "deezer_album", return_value=b) as da, mock.patch.object(notes.time, "sleep"), \
                mock.patch.object(notes.musicbrainz, "find_release_group", return_value=None):
            out = notes.albums(archive, {}, limit=1)
            self.assertEqual(out, {"b": b})
            da.reset_mock()
            da.return_value = 0
            today = datetime.date(2026, 11, 2)
            self.assertEqual(notes.albums(archive, out, limit=5, today=today), {"b": b, "a": {"miss": "2026-11-02", "fb": 1}})
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
        other = {"data": [{"id": 3, "title": "KID A MNESIA", "artist": {"name": "Radiohead"}}]}
        with mock.patch.object(notes.http, "get_json", return_value=other):  # another record, not an edition of this one
            self.assertEqual(notes.deezer_album("Radiohead", "Kid A", sleep=lambda s: None), 0)
        deluxe = {"data": [{"id": 4, "title": "Kid A (Deluxe Edition)", "artist": {"name": "Radiohead"}}]}
        long_ = {"id": 4, "nb_tracks": 3, "tracks": {"data": [{"title": "One", "duration": 1}]}}
        rest = {"data": [{"title": "One", "duration": 1}, {"title": "Two", "duration": 2}, {"title": "Three", "duration": 3}]}
        with mock.patch.object(notes.http, "get_json", side_effect=[deluxe, long_, rest]) as g:
            out = notes.deezer_album("Radiohead", "Kid A", sleep=lambda s: None)
        self.assertEqual((out["dz"], len(out["t"])), (4, 3))
        self.assertEqual(g.call_args_list[2].args[0], "https://api.deezer.com/album/4/tracks?limit=500")
        with mock.patch.object(notes.http, "get_json", return_value={"error": {"code": 4, "message": "Quota limit exceeded"}}):
            self.assertIsNone(notes.deezer_album("Radiohead", "Kid A", sleep=lambda s: None))

    def test_a_deezer_miss_gets_a_cover_and_tracks_from_musicbrainz_once(self):
        # owner, 2026-11-08: leroy «status update music» had no cover; a miss from before is asked once more
        archive = [{"id": "l", "artist_name": "leroy", "album": "status update music", "published": "2026-05-24"}]
        rg = {"rg_id": "R", "date": "2026-05-22", "releases": ["r1"]}
        caa = {"images": [{"front": False, "image": "http://x/back.jpg"},
                          {"front": True, "image": "http://x/f.jpg", "thumbnails": {"1200": "http://x/f-1200.jpg"}}]}
        with mock.patch.object(notes, "deezer_album", return_value=0), mock.patch.object(notes.time, "sleep"), \
                mock.patch.object(notes.musicbrainz, "find_release_group", return_value=rg), \
                mock.patch.object(notes.musicbrainz, "release_details", return_value={"tracks": [{"title": "A", "sec": 61}], "duration_min": 1}), \
                mock.patch.object(notes.http, "get_json", return_value=caa):
            out = notes.albums(archive, {"l": {"miss": "2026-11-02", "t": [["Kept", 5]]}}, today=datetime.date(2026, 11, 8))
        self.assertEqual(out, {"l": {"miss": "2026-11-08", "t": [["Kept", 5]], "mb": "R", "y": "2026",
                                     "cv": "https://x/f-1200.jpg", "fb": 1}})  # the table's tracklist is kept
        from lmn import site
        self.assertEqual(site.card_album(archive[0], site.deezer_found(out["l"])),
                         {"cv": "https://x/f-1200.jpg", "t": [["Kept", 5]], "y": "2026"})

    def test_the_album_comes_before_a_single_of_the_same_name(self):
        from lmn import links
        res = [{"id": 1, "title": "FENIAN", "record_type": "single", "nb_tracks": 3, "artist": {"name": "Kneecap"}},
               {"id": 2, "title": "FENIAN", "record_type": "album", "nb_tracks": 14, "artist": {"name": "Kneecap"}}]
        self.assertEqual(links.pick_album(res, ["KNEECAP"], "FENIAN")["id"], 2)

    def test_find_album_plain_words_first_then_the_field_search(self):
        from lmn import links
        vol = {"data": [{"id": 7, "title": "Vol.1", "artist": {"name": "Angine de Poitrine"}},
                        {"id": 8, "title": "Vol.II", "artist": {"name": "Angine de Poitrine"}}]}
        got = []
        get = lambda url: got.append(url) or vol
        self.assertEqual(links.find_album("Angine de Poitrine", "Vol. II", get)["id"], 8)
        self.assertEqual(got, ["https://api.deezer.com/search/album?q=Angine%20de%20Poitrine%20Vol.%20II&limit=25"])
        answers = iter([{"data": []}, {"data": [{"id": 9, "title": "Light-Years", "artist": {"name": "Nas"}}]}])
        got.clear()
        get = lambda url: got.append(url) or next(answers)
        self.assertEqual(links.find_album("Nas & DJ Premier", "Light-Years", get)["id"], 9)  # a collaboration: one of its names
        self.assertIn(urllib.parse.quote('artist:"Nas" album:"Light-Years"'), got[1])
        mega = {"data": [{"id": 1, "title": "Youthanasia", "artist": {"name": "Megadeth"}}, {"id": 2, "title": "Megadeth", "artist": {"name": "Megadeth"}}]}
        self.assertEqual(links.find_album("Megadeth", "Self-Titled", lambda url: mega)["id"], 2)
        other = {"data": [{"id": 3, "title": "The Life of a Showgirl", "artist": {"name": "Minnz Piano"}}]}
        self.assertIsNone(links.find_album("Taylor Swift", "The Life of a Showgirl", lambda url: other))
        self.assertEqual(links.credited_names("Radiohead"), ["Radiohead"])

    def test_albums_ask_misses_again_and_keep_them_when_out_of_lookups(self):
        archive = [{"id": "a", "artist_name": "A", "album": "X", "published": "2021"}, {"id": "b", "artist_name": "B", "album": "Y", "published": "2020"}]
        hit = {"dz": 5, "t": [["One", 60]]}
        with mock.patch.object(notes, "deezer_album", return_value=hit) as da, mock.patch.object(notes.time, "sleep"):
            self.assertEqual(notes.albums(archive, {"a": 0, "b": 0}, limit=1), {"a": hit, "b": 0})
            da.assert_called_once_with("A", "X")
            da.return_value = None  # the request failed: the old answer stays
            self.assertEqual(notes.albums(archive, {"a": 0}, limit=5), {"a": 0})
            da.reset_mock()
            day = datetime.date(2026, 11, 2)
            new = [{"id": "n", "artist_name": "N", "album": "Z", "published": "2026-10-20"}]
            old_ = [{"id": "o", "artist_name": "O", "album": "W", "published": "2020-01-01"}]
            # a review under 60 days old: asked again after a week; an older one after 90 days
            self.assertEqual(notes.albums(new, {"n": {"miss": "2026-10-30", "fb": 1}}, today=day), {"n": {"miss": "2026-10-30", "fb": 1}})
            self.assertEqual(notes.albums(old_, {"o": {"miss": "2026-09-01", "fb": 1}}, today=day), {"o": {"miss": "2026-09-01", "fb": 1}})
            da.assert_not_called()
            da.return_value = hit
            self.assertEqual(notes.albums(new, {"n": {"miss": "2026-10-26"}}, today=day), {"n": hit})
            self.assertEqual(notes.albums(old_, {"o": {"miss": "2026-08-01"}}, today=day), {"o": hit})

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



class VideoDates(unittest.TestCase):
    def test_archive_is_ordered_by_the_video_not_by_the_site(self):
        archive = [
            {"id": "a", "published": "2026-10-26T12:30:00.000-04:00"},                    # video found through notes.json
            {"id": "b", "published": "2026-10-26T12:36:00.000-04:00", "video_id": "vb"},  # its own video_id
            {"id": "c", "published": "2026-10-20T08:00:00.000-04:00"},                    # no video: the site's time, in UTC
            {"id": "d", "published": "2026-10-21T08:00:00.000-04:00", "video_id": "vd"},  # a wrong match, 200 days off
            {"id": "e", "published": "2026-10-29T23:04:17Z", "video_id": "ve"},           # a card from YouTube: as it is
        ]
        ups = [{"id": "va", "date": "2026-10-23T03:00:00Z"}, {"id": "vb", "date": "2026-10-21T15:00:00Z"},
               {"id": "vd", "date": "2026-04-04T15:00:00Z"}, {"id": "ve", "date": "2026-10-29T23:04:17Z"}]
        self.assertEqual(notes.use_video_dates(ups, archive, {"a": {"video_id": "va"}}), 4)
        got = {a["id"]: (a["published"], a.get("tnd_published")) for a in archive}
        self.assertEqual(got, {"a": ("2026-10-23T03:00:00Z", "2026-10-26T16:30:00Z"), "b": ("2026-10-21T15:00:00Z", "2026-10-26T16:36:00Z"),
                               "c": ("2026-10-20T12:00:00Z", None), "d": ("2026-10-21T12:00:00Z", None),
                               "e": ("2026-10-29T23:04:17Z", None)})
        self.assertEqual([a["id"] for a in sorted(archive, key=lambda a: a["published"])], ["c", "d", "b", "a", "e"])
        self.assertEqual(notes.use_video_dates(ups, archive, {"a": {"video_id": "va"}}), 0, "a second run changes nothing")

    def test_the_step_after_specials_works_on_the_fresh_archive_file(self):
        import json, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "archive.json").write_text(json.dumps([{"id": "a", "published": "2026-10-26T12:30:00.000-04:00"},
                                                        {"id": "new", "published": "2026-11-02T03:43:57Z", "video_id": "vn"}]))
            (d / "notes.json").write_text(json.dumps({"a": {"video_id": "va"}}))
            (d / "dates.json").write_text(json.dumps({"va": "2026-10-23T03:00:00Z"}))
            notes.apply_dates(d / "dates.json", d)
            self.assertEqual([x["published"] for x in json.loads((d / "archive.json").read_text())], ["2026-10-23T03:00:00Z", "2026-11-02T03:43:57Z"])


if __name__ == "__main__":
    unittest.main()
