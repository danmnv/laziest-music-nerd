import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lmn import decade_tens, gemini, site, transcribe
from tests.test_transcribe import gemini_answer


VID = "erqGhrVB5Ao"
ALBUMS = decade_tens.EPISODES[VID][2]
BRIEF = "Разбирает, как яркие мелодии сочетаются со свободной импровизацией."
ABOUT = "Подчёркивает, как музыканты меняют динамику и переходят от мелодии к свободной импровизации."
EXISTING = {
    "id": "original-zappa", "artist_name": "Frank Zappa", "album": "Hot Rats", "classic": True,
    "url": "https://theneedledrop.com/classic", "published": "2015-01-01T00:00:00Z",
}


def response_rows():
    return [{"id": key, "artist": artist, "album": title, "start_seconds": 30 + 50 * i,
             "brief": BRIEF, "about": ABOUT}
            for i, (key, artist, title, _) in enumerate(ALBUMS)]


class DecadeTensTest(unittest.TestCase):
    def test_archive_keeps_existing_record_and_adds_only_missing_albums(self):
        archive = [EXISTING.copy()]
        self.assertEqual(decade_tens.add_to_archive(archive), 24)
        self.assertEqual(decade_tens.add_to_archive(archive), 0)
        self.assertEqual(archive[0], EXISTING)
        self.assertEqual(len({a["id"] for a in archive}), 25)
        self.assertTrue(all(a["score"] == 10 and "video_id" not in a for a in archive[1:]))

    def test_response_is_per_album_with_distinct_timestamps(self):
        rows = response_rows()
        parsed = decade_tens.parse_answer(gemini_answer(json.dumps({"items": rows})), ALBUMS, 481)
        self.assertEqual(parsed["black-saint"]["start_seconds"], 130)
        self.assertEqual(parsed["black-saint"]["brief"], BRIEF)
        rows[1]["start_seconds"] = rows[0]["start_seconds"]
        with self.assertRaises(ValueError):
            decade_tens.parse_answer(gemini_answer(json.dumps({"items": rows})), ALBUMS, 481)

    def test_priority_pass_reserves_quota_and_reuses_a_cached_episode(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            def generate(body, api_key, **kwargs):
                self.assertIn(VID, body["contents"][0]["parts"][0]["fileData"]["fileUri"])
                self.assertTrue(kwargs["before_request"]("test-model", float("inf")))
                gemini.requests["test-model"] += 1
                return "test-model", gemini_answer(json.dumps({"items": response_rows()}))

            with mock.patch.object(transcribe, "DATA", data), mock.patch.object(transcribe, "minutes", return_value={VID: 8}), \
                    mock.patch.object(transcribe.notes, "albums", return_value={}), mock.patch.object(gemini, "requests", {"test-model": 0}), \
                    mock.patch.object(gemini, "generate", side_effect=generate) as mock_generate:
                budget = transcribe.RunBudget({"minutes": 10, "requests": {"test-model": 1}})
                self.assertEqual(transcribe.process_decade_tens([EXISTING], "fake-key", budget, 0), 1)
                self.assertEqual(budget.minutes_left, 2)
                self.assertEqual(transcribe.process_decade_tens([EXISTING], "fake-key", budget, 0), 0)
                mock_generate.assert_called_once()

    def test_site_uses_existing_card_and_publishes_timestamp_and_description(self):
        with tempfile.TemporaryDirectory() as d:
            data, out = Path(d, "data"), Path(d, "out")
            data.mkdir()
            (data / "archive.json").write_text(json.dumps([EXISTING]))
            items = decade_tens.parse_answer(gemini_answer(json.dumps({"items": response_rows()})), ALBUMS, 481)
            cover = {"cv": "https://example.com/cover.jpg", "t": [["Track One", 190]], "y": "1963"}
            decade_tens.save(data / decade_tens.FILENAME, {"videos": {VID: {"items": items}}, "albums": {"black-saint": cover}})
            with mock.patch.object(site, "DATA", data), mock.patch.object(site, "OUT", out):
                site.build()
            self.assertFalse((out / "r" / "ten-hot-rats.html").exists())
            for review_id, seconds in (("original-zappa", 30), ("ten-black-saint", 130)):
                page = (out / "r" / f"{review_id}.html").read_text()
                link = decade_tens.video_url(VID, seconds)
                self.assertIn(ABOUT, page)
                self.assertIn(link, page)
                payload = json.loads((out / "rt" / f"{review_id}.json").read_text())
                self.assertEqual(payload["brief"], BRIEF)
                self.assertEqual(payload["series"]["url"], link)
            page = (out / "r" / "ten-black-saint.html").read_text()
            self.assertIn("10/10", page)
            self.assertIn(cover["cv"], page)
            self.assertIn("Track One", page)
