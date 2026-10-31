"""Fantano's "Listen:" link: the album on YouTube and the artist's own release page."""
import unittest
from unittest import mock

from lmn import card, enrich as enrich_mod, http, listen, tnd, yt_archive

DESC = """New album FANGS out now: https://hmltd.lnk.to/fangs
Single: https://hmltd.lnk.to/umami.
Follow: https://instagram.com/hmltd"""


def fake_yt(playlist_title="Album - FANGS"):
    def yt(path, **kw):
        if path == "playlists":
            return {"items": [{"snippet": {"title": playlist_title}}]}
        if path == "playlistItems":
            return {"items": [{"contentDetails": {"videoId": "trackvid001"}}]}
        if path == "videos":
            assert kw["id"] == "trackvid001"
            return {"items": [{"snippet": {"description": DESC}}]}
        raise AssertionError(path)
    return yt


def pages(url, **kw):
    return {"https://hmltd.lnk.to/fangs": '<meta property="og:title" content="HMLTD - FANGS">',
            "https://hmltd.lnk.to/umami": "<title>HMLTD - Umami</title>"}[url]


class ListenTest(unittest.TestCase):
    def setUp(self):
        for p in [mock.patch.dict("os.environ", {"YOUTUBE_API_KEY": "k"}), mock.patch.object(http, "request", side_effect=pages)]:
            p.start()
            self.addCleanup(p.stop)

    def test_targets(self):
        self.assertEqual(listen.youtube_target("https://youtube.com/playlist?list=OLAK5uy_x"), ("playlist", "OLAK5uy_x"))
        self.assertEqual(listen.youtube_target("https://music.youtube.com/watch?v=abcdefghijk&list=X"), ("video", "abcdefghijk"))
        self.assertEqual(listen.youtube_target("https://youtu.be/abcdefghijk?si=1"), ("video", "abcdefghijk"))
        self.assertIsNone(listen.youtube_target("https://hmltd.bandcamp.com/album/fangs"))

    def test_album_playlist_and_its_release_page(self):
        with mock.patch.object(yt_archive, "yt", fake_yt()):
            out = listen.resolve("https://www.youtube.com/playlist?list=OLAK5uy_x", "FANGS")
        self.assertEqual(out, {"youtube_album": "https://www.youtube.com/playlist?list=OLAK5uy_x",
                               "release_page": "https://hmltd.lnk.to/fangs"})

    def test_a_playlist_or_page_not_named_after_the_album_is_not_used(self):
        with mock.patch.object(yt_archive, "yt", fake_yt("My favourite songs")):
            out = listen.resolve("https://www.youtube.com/playlist?list=PLx", "Umami Deluxe")
        self.assertEqual(out, {})

    def test_names_album(self):
        self.assertTrue(listen.names_album("Quavo 'QRÖMELIFE' Album", "QRÖMELIFE"))
        self.assertTrue(listen.names_album("c", "C"))
        self.assertTrue(listen.names_album("Remi Wolf - Mud", "Mud"))
        self.assertFalse(listen.names_album("Cool songs", "C"))
        self.assertFalse(listen.names_album("Muddy waters", "Mud"))

    def test_album_playlist_on_the_channel_of_a_track_video(self):
        def yt(path, **kw):
            if path == "videos":
                return {"items": [{"snippet": {"description": "Backwards: https://Quavo.lnk.to/Backwards", "channelId": "UCq"}}]}
            if path == "playlists":
                self.assertEqual(kw["channelId"], "UCq")
                return {"items": [{"id": "PLvids", "snippet": {"title": "Music videos"}},
                                  {"id": "PLalbum", "snippet": {"title": "Quavo 'QRÖMELIFE' Album"}}]}
            raise AssertionError(path)
        with mock.patch.object(yt_archive, "yt", yt), \
                mock.patch.object(http, "request", return_value="<title>Quavo - Backwards</title>"):
            out = listen.resolve("https://youtu.be/abcdefghijk", "QRÖMELIFE")
        self.assertEqual(out, {"youtube_album": "https://www.youtube.com/playlist?list=PLalbum"})

    def test_without_a_key_nothing_is_looked_up(self):
        with mock.patch.dict("os.environ", {"YOUTUBE_API_KEY": ""}), mock.patch.object(yt_archive, "yt", side_effect=AssertionError):
            self.assertEqual(listen.resolve("https://youtu.be/abcdefghijk", "FANGS"), {})

    def test_card_prefers_the_album_on_youtube_and_the_artists_page(self):
        rev = dict(tnd.parse_post({"id": "p", "title": "HMLTD - FANGS", "slug": "s", "url": "https://theneedledrop.com/x/",
                                   "published_at": "2026-10-30T10:00:00+00:00", "canonical_url": "",
                                   "tags": [{"name": "Album Reviews"}, {"name": "5/10"}]}),
                   listen_url="https://www.youtube.com/playlist?list=OLAK5uy_x")
        dz = {"id": 1, "url": "https://www.deezer.com/album/1", "cover": None, "duration_min": 44, "tracks": [{"title": "A", "sec": 1}]}
        with mock.patch.object(yt_archive, "yt", fake_yt()), mock.patch.object(enrich_mod.mb, "find_release_group", return_value=None), \
                mock.patch.object(enrich_mod.links, "deezer_album", return_value=dz):
            r = enrich_mod.enrich(rev, "text", [], use_ai=False)
        self.assertEqual(r["links"]["songlink"], "https://hmltd.lnk.to/fangs")
        texts = [b["text"] for row in card.buttons(r) for b in row]
        self.assertIn("YouTube (альбом)", texts)
        self.assertNotIn("YouTube Music", texts)


if __name__ == "__main__":
    unittest.main()
