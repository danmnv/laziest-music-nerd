import unittest
from unittest import mock

from lmn import check, enrich, links, refresh
from test_check import FakeTelegram

ESTUARY = {"fav_tracks": ["KNIGHTS OF TIAMAT", "FORETOLD IN REFLECTIONS", "THE ORCA CLIFFS", "WRETCHED SPIRITS", "LAND OF LIGHT"],
           "least_fav_track": "GHOSTS AMONG THE OBELISKS"}


class FitsTest(unittest.TestCase):
    def test_an_advance_single_is_not_the_album(self):
        # Wolves in the Throne Room «Estuary», 2026-11-10: Deezer had only the 2-track single
        single = [{"title": "Estuary", "sec": 426}, {"title": "Ghosts Among the Obelisks", "sec": 520}]
        self.assertFalse(links.fits(enrich.named_tracks(ESTUARY), single))
        self.assertFalse(links.fits(["THIS IS WHY", "THE NEWS", "RUNNING OUT OF TIME"], [["This Is Why", 206]]))

    def test_what_fits(self):
        album = [{"title": t} for t in ["Knights of Tiamat", "Foretold in Reflections", "The Orca Cliffs", "Land of Light"]]
        self.assertTrue(links.fits(enrich.named_tracks(ESTUARY), album))
        self.assertTrue(links.fits(["BURGUNDY FT. VINCE STAPLES", "CHUM"], [["Burgundy (feat. Vince Staples)", 1], ["Chum", 1]]))
        self.assertTrue(links.fits(["KANNON PT. 2", "KANNON PT. 3"], [["Kannon1", 1], ["Kannon2", 1], ["Kannon3", 1]]))
        self.assertTrue(links.fits(["Part I", "Part III"], [["Widowmaker Part. 1", 1]]))  # too short to be names
        self.assertTrue(links.fits(["SOLE"], [["Never Enough", 1]]))  # one name proves nothing
        self.assertTrue(links.fits(["A1", "B2", "C3"], [[str(i), 1] for i in range(6)]))  # a long tracklist always fits
        self.assertTrue(links.fits([], [["X", 1]]))


class AlbumFoundLaterTest(unittest.TestCase):
    def test_its_cover_goes_first_and_replaces_the_posts_picture(self):
        r = {"id": "z", "tg_channel_msg": 14, "tg_kind": "photo", "covers": ["https://coverartarchive.org/x", "https://i.ytimg.com/y"]}
        refresh.fill(r, {"tracks": [{"title": "Knights of Tiamat", "sec": 1}], "covers": ["https://cdn-images.dzcdn.net/a.jpg", "https://coverartarchive.org/x"]})
        self.assertEqual(r["covers"][0], "https://cdn-images.dzcdn.net/a.jpg")
        self.assertEqual(r["new_cover"], 1)
        tg = FakeTelegram()
        tg.photos = []
        tg.edit_photo = lambda chat, mid, url, text, kb: tg.photos.append((mid, url))
        with mock.patch("lmn.card.caption", return_value="caption"):
            check.edit_card(tg, "@c", r, [])
        self.assertEqual(tg.photos, [(14, "https://cdn-images.dzcdn.net/a.jpg")])
        self.assertNotIn("new_cover", r)


if __name__ == "__main__":
    unittest.main()
