import json
import tempfile
import unittest
from pathlib import Path

from lmn import aoty_top


ROW = {"found_artist": "Beyoncé", "found_title": "Lemonade", "found_release_date": "April 23, 2016", "critic_score": "9.2",
       "critic_reviews": json.dumps([{"publication": "Pitchfork", "rating": "8.5"}]),
       "album_details_v2": json.dumps({"genre_primary": ["Contemporary R&B", "Festival Progressive House Music"], "genre_secondary": ["Art Pop"],
                                       "tracklist": [{"title": "Pray You Catch Me", "length": "3:16"}, {"title": "Hold Up", "length": "3:41"}]}),
       "streaming_links_from_album": json.dumps({"apple_music": "https://geo.music.apple.com/us/album/lemonade/1?at=aff&ct=x",
                                                 "soundcloud": "https://soundcloud.com/beyonce/sets/lemonade", "spotify": "https://open.spotify.com/x"})}


class AotyTopTest(unittest.TestCase):
    def test_key_and_shard(self):
        self.assertEqual(aoty_top.key("Beyoncé", "Lemonade (Deluxe)"), "beyonce--lemonade")
        self.assertEqual(aoty_top.key("Simon & Garfunkel", "“Bookends”"), "simonandgarfunkel--bookends")
        self.assertEqual(aoty_top.shard("m--m"), "m-")
        self.assertEqual(aoty_top.shard("ものんくる--x"), "__")

    def test_entry_is_compact(self):
        e = aoty_top.entry(ROW)
        self.assertEqual(e["d"], "2016-04-23")
        self.assertEqual(e["g"], ["contemporary r&b", "art pop"])  # the long name left out
        self.assertEqual(e["tr"], [["Pray You Catch Me", 196], ["Hold Up", 221]])
        self.assertEqual(e["am"], "https://music.apple.com/us/album/lemonade/1")  # no affiliate parameters
        self.assertEqual(e["sc"], "https://soundcloud.com/beyonce/sets/lemonade")
        self.assertNotIn("spotify", json.dumps(e))

    def test_genres_filled_to_three_without_repeats(self):
        self.assertEqual(aoty_top.add_genres(["pop"], ["art pop", "hip hop", "hip-hop", "soul", "jazz"]), ["pop", "hip hop", "soul"])
        self.assertEqual(aoty_top.add_genres(["a", "b", "c"], ["d"]), ["a", "b", "c"])

    def test_apply_fills_only_empty_places(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            top = {"beyonce--lemonade": aoty_top.entry(ROW)}
            (d / "aoty_top.json").write_text(json.dumps(top))
            (d / "archive.json").write_text(json.dumps([{"id": "v1", "artist_name": "Beyoncé", "album": "Lemonade", "genres": ["r&b"]},
                                                        {"id": "v2", "artist_name": "Other", "album": "Thing"}]))
            (d / "apple.json").write_text(json.dumps({"v1": "https://music.apple.com/mine"}))
            (d / "bandcamp.json").write_text("{}")
            (d / "aoty.json").write_text("{}")
            (d / "albums.json").write_text(json.dumps({"v1": {"miss": "2026-11-01"}}))
            import io, contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                counts = aoty_top.apply(d)
            self.assertEqual(json.loads((d / "apple.json").read_text())["v1"], "https://music.apple.com/mine")  # kept
            self.assertEqual(json.loads((d / "albums.json").read_text())["v1"]["t"][0], ["Pray You Catch Me", 196])
            self.assertEqual(json.loads((d / "aoty.json").read_text())["v1"]["s"], 92)
            self.assertEqual(json.loads((d / "archive.json").read_text())[0]["genres"], ["r&b", "art pop"])  # "contemporary r&b" repeats "r&b"
            self.assertEqual(counts["apple"], 0)


if __name__ == "__main__":
    unittest.main()
