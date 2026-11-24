import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lmn import aoty_top, apple, links, notes, site


class AlbumEditionTest(unittest.TestCase):
    def test_search_does_not_strip_album_nicknames(self):
        named = {"id": 1, "title": "Weezer (Teal Album)", "artist": {"name": "Weezer"}}
        gold = {"id": 2, "title": "Weezer", "artist": {"name": "Weezer"}}
        white = {"id": 3, "title": "Weezer (White Album)", "artist": {"name": "Weezer"}}
        remastered = {"id": 4, "title": "Weezer (Teal Album) [2019 Remaster]", "artist": {"name": "Weezer"}}
        self.assertEqual(links.pick_album([gold, white, remastered, named], ["Weezer"], "Weezer (The Teal Album)"), named)
        self.assertEqual(links.pick_album([remastered], ["Weezer"], "Weezer (The Teal Album)"), remastered)
        self.assertIsNone(links.pick_album([named, white], ["Weezer"], "Weezer", editions=True))

    def test_apple_lookup_and_search_validate_the_album_title(self):
        gold = {"wrapperType": "collection", "artistName": "Weezer", "collectionName": "Weezer",
                "collectionViewUrl": "https://music.apple.com/us/album/weezer/2",
                "artworkUrl100": "https://example.com/gold/100x100bb.jpg"}
        teal = {**gold, "collectionName": "Weezer (Teal Album)",
                "collectionViewUrl": "https://music.apple.com/us/album/teal/1",
                "artworkUrl100": "https://example.com/teal/100x100bb.jpg"}
        with patch.object(links.http, "get_json", return_value={"results": [gold, teal]}):
            self.assertEqual(links.apple_find("Weezer", "Weezer (The Teal Album)"), teal["collectionViewUrl"])
        with patch.object(links.http, "get_json", return_value={"results": [teal]}):
            self.assertEqual(links.apple_find("Weezer", "Weezer"), 0)
            self.assertEqual(links.apple_tracks(teal["collectionViewUrl"], "Weezer", "Weezer (The Teal Album)")["cover"],
                             "https://example.com/teal/1000x1000bb.jpg")
        with patch.object(links.http, "get_json", return_value={"results": [gold]}):
            self.assertIsNone(links.apple_tracks(gold["collectionViewUrl"], "Weezer", "Weezer (The Teal Album)"))

    def test_imported_row_has_to_match_the_reviewed_edition(self):
        key = aoty_top.key("Weezer", "Weezer (White Album)")
        top = {key: {"a": "Weezer", "t": "Weezer (White Album)", "am": "white"}}
        archive = [{"id": "teal", "artist_name": "Weezer", "album": "Weezer (The Teal Album)"},
                   {"id": "white", "artist_name": "Weezer", "album": "Weezer (The White Album)"}]
        self.assertEqual(aoty_top.reviewed(archive, top), {"white": top[key]})

    def test_cached_weezer_cards_get_the_verified_edition(self):
        examples = [
            ("6684c32c49ea2a054e092477", "Weezer (The Teal Album)", "2019", "1450270988", "Africa"),
            ("6684c32c49ea2a054e0920a9", "Weezer (The White Album)", "2016", "1100739016", "California Kids"),
            ("6684c32c49ea2a054e09248e", "Weezer (Black Album)", "2019", "1442329821", "Can't Knock the Hustle"),
            ("6a8d3ead93fb940337491c90", "Self-Titled (Gold)", "2026", "6772364953", "Say Yes"),
        ]
        archive = [{"id": i, "artist_name": "Weezer", "album": title, "published": f"{year}-12-01",
                    "url": "https://example.com/review", "score": 5} for i, title, year, _, _ in examples]
        wrong_cv = "https://example.com/gold.jpg"
        stale = {i: {"cv": wrong_cv, "t": [["Wrong", 1]], "miss": "2026-11-01"} for i, *_ in examples}
        stale_apple = {i: "https://music.apple.com/us/album/weezer/6772364953" for i, *_ in examples}
        updated = notes.albums(archive, stale, limit=0)
        updated_apple = apple.run(archive, stale_apple, limit=0)
        self.assertTrue(all(updated[i]["cv"] != wrong_cv for i, *_ in examples))
        self.assertTrue(all(updated_apple[i].endswith(f"/{am}") for i, _, _, am, _ in examples))

        with tempfile.TemporaryDirectory() as tmp:
            data, output = Path(tmp, "data"), Path(tmp, "site")
            data.mkdir()
            for path, content in (("archive.json", archive), ("albums.json", stale), ("apple.json", stale_apple)):
                (data / path).write_text(json.dumps(content))
            with patch.multiple(site, DATA=data, OUT=output):
                site.build()
            covers = set()
            for i, title, year, am, first in examples:
                with self.subTest(title=title):
                    rt = json.loads((output / "rt" / f"{i}.json").read_text())
                    self.assertTrue(rt["apple"].endswith(f"/{am}"))
                    self.assertEqual(rt["al"]["y"], year)
                    self.assertEqual(rt["al"]["t"][0][0], first)
                    self.assertNotEqual(rt["al"]["cv"], wrong_cv)
                    self.assertIn(f'src="{rt["al"]["cv"]}"', (output / "r" / f"{i}.html").read_text())
                    covers.add(rt["al"]["cv"])
            self.assertEqual(len(covers), len(examples))

    def test_bully_full_album_belongs_only_to_the_2026_review(self):
        early, current = "67ec9e8ba176bb07ab370e71", "69cdd0bac4ab5e049cd37b65"
        archive = [{"id": i, "artist_name": artist, "album": "Bully", "published": date, "url": "https://example.com/review"}
                   for i, artist, date in [(early, "Kanye West", "2025-04-02"), (current, "Ye", "2026-04-02")]]
        stale = {early: {"dz": 949407771, "y": "2026"}, current: {"dz": 907177312, "y": "2025"}}
        with tempfile.TemporaryDirectory() as tmp:
            data, output = Path(tmp, "data"), Path(tmp, "site")
            data.mkdir()
            (data / "archive.json").write_text(json.dumps(archive))
            (data / "albums.json").write_text(json.dumps(stale))
            with patch.multiple(site, DATA=data, OUT=output):
                site.build()
            original = json.loads((output / "rt" / f"{early}.json").read_text())
            self.assertEqual(original["al"], {"miss": 1, "no_streaming": True})
            self.assertNotIn("apple", original)
            album = json.loads((output / "rt" / f"{current}.json").read_text())
            self.assertTrue(album["apple"].endswith("/1888707282"))
            self.assertEqual(album["al"]["y"], "2026")
            self.assertEqual(len(album["al"]["t"]), 18)
            self.assertEqual(album["al"]["t"][0][0], "KING")
